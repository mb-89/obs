(() => {
    const INCOMPLETE = "still typing";

    const incomplete = () => new Error(INCOMPLETE);

    const lex = (source) => {
        const tokens = [];
        const characters = Array.from(source);
        let index = 0;
        while (index < characters.length) {
            const character = characters[index];
            if (character === " " || character === "\t") {
                index += 1;
            } else if (character === "(" || character === ")") {
                tokens.push({ kind: character, text: character });
                index += 1;
            } else if (character === ":") {
                tokens.push({ kind: "colon", text: character });
                index += 1;
            } else if (character === '"') {
                let end = index + 1;
                let text = "";
                while (end < characters.length && characters[end] !== '"') {
                    if (characters[end] === "\\" && ["\\", '"'].includes(characters[end + 1])) {
                        text += characters[end + 1];
                        end += 2;
                    } else {
                        text += characters[end];
                        end += 1;
                    }
                }
                if (end >= characters.length) throw incomplete();
                tokens.push({ kind: "quoted", text });
                index = end + 1;
            } else if (character === "/") {
                let end = index + 1;
                while (end < characters.length && characters[end] !== "/") {
                    if (characters[end] === "\\") end += 1;
                    end += 1;
                }
                if (end >= characters.length) throw incomplete();
                tokens.push({ kind: "regex", text: characters.slice(index + 1, end).join("") });
                index = end + 1;
            } else {
                let end = index;
                while (end < characters.length && !" \t():\"".includes(characters[end])) end += 1;
                const text = characters.slice(index, end).join("");
                const operator = text.toLocaleLowerCase();
                tokens.push({
                    kind: ["and", "or", "not"].includes(operator) ? operator : "word",
                    text,
                });
                index = end;
            }
        }
        return tokens;
    };

    const quotePattern = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

    class Clause {
        constructor(field, value) {
            this.field = field.toLocaleLowerCase();
            this.needle = null;
            this.pattern = null;
            if (value.kind === "regex") {
                this.pattern = value.text;
                new RegExp(this.pattern, "i");
            } else if (value.text.includes("*")) {
                this.pattern = value.text.split("*").map(quotePattern).join(".*");
            } else {
                this.needle = value.text.toLocaleLowerCase();
            }
        }

        value(record) {
            if (!this.field) return record.haystack;
            if (this.field === "detail" || this.field === "details") return record.detail;
            return record.fields[this.field];
        }

        hit(value) {
            if (value === undefined) return false;
            if (Array.isArray(value)) return value.some((item) => this.hit(item));
            const text = String(value);
            if (this.pattern !== null) return new RegExp(this.pattern, "i").test(text);
            return text.toLocaleLowerCase().includes(this.needle);
        }

        match(record) {
            return this.hit(this.value(record));
        }

        appliesTo(field) {
            if (!this.field) return true;
            if (field === "text") {
                return ["text", "content", "body", "detail", "details"].includes(this.field);
            }
            return this.field === field;
        }

        ranges(value, field) {
            if (!this.appliesTo(field)) return [];
            if (this.pattern !== null) {
                const ranges = [];
                const expression = new RegExp(this.pattern, "gi");
                for (const match of value.matchAll(expression)) {
                    if (match[0].length) ranges.push([match.index, match.index + match[0].length]);
                }
                return ranges;
            }
            const ranges = [];
            const lower = value.toLocaleLowerCase();
            let start = lower.indexOf(this.needle);
            while (this.needle && start >= 0) {
                ranges.push([start, start + this.needle.length]);
                start = lower.indexOf(this.needle, start + this.needle.length);
            }
            return ranges;
        }
    }

    class Parser {
        constructor(tokens) {
            this.tokens = tokens;
            this.index = 0;
        }

        peek() {
            return this.tokens[this.index]?.kind || "";
        }

        parseOr() {
            let left = this.parseAnd();
            while (this.peek() === "or") {
                this.index += 1;
                left = { kind: "or", left, right: this.parseAnd() };
            }
            return left;
        }

        parseAnd() {
            let left = this.parseUnary();
            while (true) {
                if (this.peek() === "and") {
                    this.index += 1;
                } else if (!["word", "quoted", "regex", "(", "not"].includes(this.peek())) {
                    return left;
                }
                left = { kind: "and", left, right: this.parseUnary() };
            }
        }

        parseUnary() {
            if (this.peek() === "not") {
                this.index += 1;
                return { kind: "not", child: this.parseUnary() };
            }
            return this.parsePrimary();
        }

        parsePrimary() {
            if (this.peek() === "(") {
                this.index += 1;
                const node = this.parseOr();
                if (this.peek() !== ")") throw incomplete();
                this.index += 1;
                return node;
            }
            if (["word", "quoted", "regex"].includes(this.peek())) return this.parseClause();
            if (!this.peek()) throw incomplete();
            throw new Error(`cannot read "${this.tokens[this.index].text}"`);
        }

        parseClause() {
            const first = this.tokens[this.index];
            this.index += 1;
            if (["word", "quoted"].includes(first.kind) && this.peek() === "colon") {
                const negated = first.kind === "word" && first.text.startsWith("-");
                const field = negated ? first.text.slice(1) : first.text;
                this.index += 1;
                const clause = new Clause(field, this.value());
                return negated ? { kind: "not", child: clause } : clause;
            }
            if (first.kind === "word" && first.text.startsWith("-") && first.text.length > 1) {
                return { kind: "not", child: new Clause("", { kind: "word", text: first.text.slice(1) }) };
            }
            return new Clause("", first);
        }

        value() {
            if (!["word", "quoted", "regex"].includes(this.peek())) throw incomplete();
            const value = this.tokens[this.index];
            this.index += 1;
            return value;
        }
    }

    const matchNode = (node, record) => {
        if (node instanceof Clause) return node.match(record);
        if (node.kind === "and") return matchNode(node.left, record) && matchNode(node.right, record);
        if (node.kind === "or") return matchNode(node.left, record) || matchNode(node.right, record);
        return !matchNode(node.child, record);
    };

    const positiveClauses = (node, positive = true) => {
        if (node instanceof Clause) return positive ? [node] : [];
        if (node.kind === "not") return positiveClauses(node.child, !positive);
        return [
            ...positiveClauses(node.left, positive),
            ...positiveClauses(node.right, positive),
        ];
    };

    const clauseFields = (node) => {
        if (node instanceof Clause) return node.field ? [node.field] : [];
        if (node.kind === "not") return clauseFields(node.child);
        return [...clauseFields(node.left), ...clauseFields(node.right)];
    };

    const mergeRanges = (ranges) => {
        const sorted = ranges.sort((left, right) => left[0] - right[0] || left[1] - right[1]);
        const merged = [];
        sorted.forEach((range) => {
            const previous = merged.at(-1);
            if (previous && range[0] <= previous[1]) previous[1] = Math.max(previous[1], range[1]);
            else merged.push([...range]);
        });
        return merged;
    };

    const compile = (source) => {
        const tokens = lex(source);
        if (!tokens.length) {
            return { source, empty: true, fields: [], match: () => true, ranges: () => [] };
        }
        tokens.filter((token) => token.kind === "regex").forEach((token) => new RegExp(token.text, "i"));
        const parser = new Parser(tokens);
        const root = parser.parseOr();
        if (parser.index !== tokens.length) throw new Error(`cannot read "${tokens[parser.index].text}"`);
        const clauses = positiveClauses(root);
        return {
            source,
            empty: false,
            fields: [...new Set(clauseFields(root))],
            match: (record) => matchNode(root, record),
            ranges: (value, field = "") => {
                const fields = Array.isArray(field) ? field : [field];
                return mergeRanges(fields.flatMap((candidate) =>
                    clauses.flatMap((clause) => clause.ranges(value, candidate)),
                ));
            },
        };
    };

    const exactClause = (field, value) => {
        const pattern = String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replaceAll("/", "\\/");
        const name = /^[A-Za-z][\w.-]*$/.test(field) ? field : JSON.stringify(field);
        return `${name}: /^${pattern}$/`;
    };
    const conditionsExpression = (conditions = []) => conditions.map((condition) =>
        "equals" in condition ? exactClause(condition.field, condition.equals)
            : `${JSON.stringify(condition.field)}: /\\S/`,
    ).join(" AND ");
    // Query conditions compare text by capabilities/queries#Conditions, as the core's
    // conditions_select does: a property resolves like a Bases property, and a missing
    // property or null has no text.
    const conditionTexts = (value) => {
        if (Array.isArray(value)) return value.flatMap(conditionTexts);
        if (value === undefined || value === null || typeof value === "object") return [];
        return [typeof value === "boolean" ? (value ? "true" : "false") : String(value)];
    };
    const conditionValue = (record, field) => {
        const value = record.frontmatter ? globalThis.obsBases.recordValue(record, field) : undefined;
        return value === undefined ? record.fields?.[field.toLocaleLowerCase()] : value;
    };
    const conditionsMatch = (record, conditions = []) => conditions.every((condition) => {
        const texts = conditionTexts(conditionValue(record, condition.field));
        return "equals" in condition ? texts.includes(condition.equals)
            : texts.some((text) => text.trim() !== "");
    });
    const compileConditions = (conditions) => ({match: (record) => conditionsMatch(record, conditions || [])});

    globalThis.obsQuery = {compile, exactClause, conditionsExpression, conditionsMatch, compileConditions,
        incomplete: INCOMPLETE};
})();