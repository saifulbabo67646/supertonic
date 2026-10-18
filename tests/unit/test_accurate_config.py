"""Settings of the ``accurate`` method (torch-free: runs everywhere)."""

from __future__ import annotations

import pytest

from supertonic_server.builder.extract.accurate.config import (
    STEPS_ENV,
    AccurateConfig,
    config_from_env,
)
from supertonic_server.builder.extract.accurate.utterances import texts


def test_defaults_are_the_global_constraints() -> None:
    cfg = AccurateConfig()
    assert (cfg.lr, cfg.lr_patience, cfg.lr_factor, cfg.min_lr) == (2e-4, 200, 0.5, 2e-6)
    assert (cfg.grad_clip, cfg.num_steps, cfg.threshold) == (1.0, 3000, 0.015)
    assert (cfg.vocoder_steps, cfg.speed, cfg.seed) == (6, 1.05, 49)
    assert (cfg.sizing_preset, cfg.log_every) == ("F4", 8)


def test_steps_env_overrides_num_steps() -> None:
    assert config_from_env({}).num_steps == 3000
    assert config_from_env({STEPS_ENV: "200"}).num_steps == 200
    assert config_from_env({STEPS_ENV: " 12 "}).num_steps == 12


@pytest.mark.parametrize("value", ["", "abc", "0", "-5", "1.5"])
def test_bad_steps_env_is_rejected(value: str) -> None:
    with pytest.raises(ValueError, match=STEPS_ENV):
        config_from_env({STEPS_ENV: value})


def test_training_texts_are_upstreams_sixteen_english_lines() -> None:
    assert len(texts) == 16
    assert {lang for lang, _ in texts} == {"en"}
    assert texts[0][1].startswith("I don't like the terms good person or bad person")
    assert texts[-1][1].endswith("maybe you need to work a little harder")
