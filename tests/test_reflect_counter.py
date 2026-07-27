"""Tests for the per-session bash-call counter."""

from hookslib import reflect_counter


class TestCounter:
    def test_increment_creates_state_file(self, tmp_path):
        path = tmp_path / "session-abc"
        n = reflect_counter.increment(path)
        assert n == 1
        assert (path / "bash-count").exists()

    def test_increment_persists_across_calls(self, tmp_path):
        path = tmp_path / "session-abc"
        reflect_counter.increment(path)
        reflect_counter.increment(path)
        n = reflect_counter.increment(path)
        assert n == 3

    def test_should_fire_at_threshold_multiples(self):
        assert reflect_counter.should_fire(100) is True
        assert reflect_counter.should_fire(200) is True
        assert reflect_counter.should_fire(300) is True

    def test_should_not_fire_off_threshold(self):
        assert reflect_counter.should_fire(0) is False
        assert reflect_counter.should_fire(5) is False
        assert reflect_counter.should_fire(10) is False
        assert reflect_counter.should_fire(99) is False

    def test_custom_threshold(self):
        assert reflect_counter.should_fire(5, threshold=5) is True
        assert reflect_counter.should_fire(10, threshold=5) is True
        assert reflect_counter.should_fire(7, threshold=5) is False
