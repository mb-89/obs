import json
from pathlib import Path
import subprocess


def test_base_null_comparisons_preserve_typed_empty_values():
    root = Path(__file__).resolve().parents[1]
    script = r"""
const fs = require("node:fs");
const vm = require("node:vm");
globalThis.document = {querySelector: () => ({textContent: fs.readFileSync("src/obs_html_interim/base.schema.json", "utf8")})};
for (const name of ["query.js", "base.js"]) {
    vm.runInThisContext(fs.readFileSync(`src/obs_html_interim/${name}`, "utf8"));
}
const values = [undefined, null, "", "  ", [], {}, [null, ""], {a: ""},
    false, 0, "null", [false], {a: 0}, "finding"];
const rows = values.map(value => ({values: {value, kind: "path"}}));
const valueFor = (row, field) => row.values[field];
const present = obsBases.compileFilter('value != null', valueFor);
const absent = obsBases.compileFilter('value == null', valueFor);
const nested = obsBases.compileFilter({and: [
    'kind == "path"', {not: ['value == null']},
]}, valueFor);
console.log(JSON.stringify({
    present: rows.map(row => present.match(row)),
    absent: rows.map(row => absent.match(row)),
    nested: rows.map(row => nested.match(row)),
}));
"""
    result = subprocess.run(
        ["node", "-e", script], cwd=root, capture_output=True, text=True, check=True,
    )
    actual = json.loads(result.stdout)
    expected = [False] * 2 + [True] * 12
    assert actual["present"] == actual["nested"] == expected
    assert actual["absent"] == [not value for value in expected]
