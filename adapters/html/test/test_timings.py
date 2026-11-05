from obs_html import timings


def test_nested_stages_record_exclusive_durations(monkeypatch) -> None:
    clock = iter([0.0, 1.0, 3.0, 6.0])
    monkeypatch.setattr(timings, "perf_counter", lambda: next(clock))
    with timings.recording() as recorded:
        with timings.stage("outer"):
            with timings.stage("inner"):
                pass
    assert recorded.durations == {"outer": 4.0, "inner": 2.0}


def test_stages_outside_a_recording_are_free(monkeypatch) -> None:
    monkeypatch.setattr(timings, "perf_counter", lambda: (_ for _ in ()).throw(AssertionError("timed")))
    with timings.stage("free"):
        pass
