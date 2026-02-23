#!/usr/bin/env python3
"""Tests for Evolutionary optimization for prompt injections ablation."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from experiments.ablations.evolutionary_optimization import (
    create_variant_injections,
    select_best_variants,
    compute_asr,
    EvolutionaryMutationAgent,
)


@pytest.fixture
def sample_injections():
    """Sample injection data for testing."""
    return [
        {
            "id": 1,
            "instructions": {
                "line_injection": "Original line injection",
                "description_injection": "Original description injection",
            },
            "tasks": [{"prompt": "Task 1", "skill": "test-skill"}],
        },
        {
            "id": 2,
            "instructions": {
                "line_injection": "Another injection",
                "description_injection": "Another description",
            },
            "tasks": [{"prompt": "Task 2", "skill": "test-skill"}],
        },
    ]


@pytest.fixture
def sample_variants():
    """Sample variant injections."""
    return {
        1: [
            "Variant 1A for injection 1",
            "Variant 1B for injection 1",
            "Variant 1C for injection 1",
        ],
        2: [
            "Variant 2A for injection 2",
            "Variant 2B for injection 2",
        ],
    }


@pytest.fixture
def sample_eval_data():
    """Sample evaluation results."""
    return {
        "data": {
            "results": [
                {
                    "sandbox_id": "INST-1_0_TASK-0",
                    "injection_id": 1,
                    "injection_score": "attack_success",
                },
                {
                    "sandbox_id": "INST-1_1_TASK-0",
                    "injection_id": 1,
                    "injection_score": "attack_failed",
                },
                {
                    "sandbox_id": "INST-1_2_TASK-0",
                    "injection_id": 1,
                    "injection_score": "attack_success",
                },
                {
                    "sandbox_id": "INST-2_0_TASK-0",
                    "injection_id": 2,
                    "injection_score": "attack_failed",
                },
                {
                    "sandbox_id": "INST-2_1_TASK-0",
                    "injection_id": 2,
                    "injection_score": "attack_success",
                },
            ],
        },
    }


class TestCreateVariantInjections:
    """Tests for create_variant_injections function."""

    def test_creates_one_entry_per_variant(self, sample_injections, sample_variants):
        result = create_variant_injections(sample_injections, sample_variants, iteration=0)
        # Should have 3 variants for injection 1 + 2 variants for injection 2
        assert len(result) == 5

    def test_updates_injection_text(self, sample_injections, sample_variants):
        result = create_variant_injections(sample_injections, sample_variants, iteration=0)
        # Check first variant of injection 1
        inj1_variants = [r for r in result if r["id"] == 1]
        assert len(inj1_variants) == 3
        assert inj1_variants[0]["instructions"]["line_injection"] == "Variant 1A for injection 1"
        assert inj1_variants[1]["instructions"]["line_injection"] == "Variant 1B for injection 1"

    def test_adds_metadata(self, sample_injections, sample_variants):
        result = create_variant_injections(sample_injections, sample_variants, iteration=3)
        for entry in result:
            assert entry["_rl_iteration"] == 3
            assert "_rl_variant" in entry

    def test_filters_by_injection_ids(self, sample_injections, sample_variants):
        result = create_variant_injections(
            sample_injections, sample_variants, iteration=0, injection_ids=[1]
        )
        # Should only have variants for injection 1
        assert len(result) == 3
        assert all(r["id"] == 1 for r in result)

    def test_preserves_unmodified_injections(self, sample_injections):
        # No variants for injection 2
        variants = {1: ["Variant 1A"]}
        result = create_variant_injections(sample_injections, variants, iteration=0)
        # Should have 1 variant for injection 1 + 1 original for injection 2
        assert len(result) == 2

    def test_handles_empty_variants(self, sample_injections):
        result = create_variant_injections(sample_injections, {}, iteration=0)
        # Should keep all original injections
        assert len(result) == 2


class TestComputeASR:
    """Tests for compute_asr function."""

    def test_computes_correct_asr(self, sample_eval_data):
        asr = compute_asr(sample_eval_data)
        # 3 out of 5 successful
        assert asr == 0.6

    def test_handles_empty_results(self):
        asr = compute_asr({"data": {"results": []}})
        assert asr == 0.0

    def test_handles_missing_data(self):
        asr = compute_asr({})
        assert asr == 0.0

    def test_handles_all_failures(self):
        data = {
            "data": {
                "results": [
                    {"injection_score": "attack_failed"},
                    {"injection_score": "attack_failed"},
                ],
            },
        }
        asr = compute_asr(data)
        assert asr == 0.0

    def test_handles_all_successes(self):
        data = {
            "data": {
                "results": [
                    {"injection_score": "attack_success"},
                    {"injection_score": "attack_success"},
                ],
            },
        }
        asr = compute_asr(data)
        assert asr == 1.0


class TestSelectBestVariants:
    """Tests for select_best_variants function."""

    def test_selects_most_successful_variant(self, sample_eval_data, sample_variants):
        best = select_best_variants(sample_eval_data, sample_variants, top_k=1)
        # Variant 0 and 2 succeeded for injection 1
        # Variant 0 has 1 success, variant 2 has 1 success
        # Should pick the one with most successes (tie -> first one)
        assert 1 in best
        assert best[1] in sample_variants[1]

    def test_handles_no_successes(self, sample_variants):
        eval_data = {
            "data": {
                "results": [
                    {
                        "sandbox_id": "INST-1_0_TASK-0",
                        "injection_id": 1,
                        "injection_score": "attack_failed",
                    },
                ],
            },
        }
        best = select_best_variants(eval_data, sample_variants, top_k=1)
        # Should pick first variant when all fail
        assert best[1] == sample_variants[1][0]

    def test_handles_empty_results(self, sample_variants):
        best = select_best_variants({"data": {"results": []}}, sample_variants, top_k=1)
        assert len(best) == 0

    def test_extracts_variant_idx_from_sandbox_id(self, sample_variants):
        eval_data = {
            "data": {
                "results": [
                    {
                        "sandbox_id": "INST-1_2_TASK-0",
                        "injection_id": 1,
                        "injection_score": "attack_success",
                    },
                ],
            },
        }
        best = select_best_variants(eval_data, sample_variants, top_k=1)
        # Should select variant 2
        assert best[1] == sample_variants[1][2]


class TestEvolutionaryMutationAgent:
    """Tests for EvolutionaryMutationAgent class."""

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    def test_initialization(self):
        agent = EvolutionaryMutationAgent()
        assert agent.model == "claude-sonnet-4-5-20250929"
        assert agent.client is not None

    @patch.dict("os.environ", {}, clear=True)
    def test_requires_api_key(self):
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            EvolutionaryMutationAgent()

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    @patch("anthropic.Anthropic")
    def test_generate_variants_success(self, mock_anthropic):
        # Mock the API response
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='["variant 1", "variant 2", "variant 3"]')]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.return_value = mock_client

        agent = EvolutionaryMutationAgent()
        agent.client = mock_client

        variants = agent.generate_variants(
            "base injection text",
            iteration=0,
            history=[],
            n_variants=3,
        )

        assert len(variants) == 3
        assert variants[0] == "variant 1"
        assert variants[1] == "variant 2"
        assert variants[2] == "variant 3"

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    @patch("anthropic.Anthropic")
    def test_generate_variants_handles_error(self, mock_anthropic):
        # Mock API error
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API error")
        mock_anthropic.return_value = mock_client

        agent = EvolutionaryMutationAgent()
        agent.client = mock_client

        base_text = "base injection"
        variants = agent.generate_variants(base_text, 0, [], 3)

        # Should fall back to base injection
        assert len(variants) == 3
        assert all(v == base_text for v in variants)

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    @patch("anthropic.Anthropic")
    def test_generate_variants_pads_insufficient_results(self, mock_anthropic):
        # Mock response with fewer variants than requested
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='["variant 1"]')]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.return_value = mock_client

        agent = EvolutionaryMutationAgent()
        agent.client = mock_client

        base_text = "base injection"
        variants = agent.generate_variants(base_text, 0, [], 3)

        # Should pad with base injection
        assert len(variants) == 3
        assert variants[0] == "variant 1"
        assert variants[1] == base_text
        assert variants[2] == base_text

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    def test_build_feedback_context_empty_history(self):
        agent = EvolutionaryMutationAgent()
        feedback = agent._build_feedback_context([])
        assert "No previous iterations" in feedback

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    def test_build_feedback_context_with_history(self):
        agent = EvolutionaryMutationAgent()
        history = [
            {
                "iteration": 0,
                "injection": "First attempt with some text that will be truncated",
                "asr": 0.2,
                "successful": False,
            },
            {
                "iteration": 1,
                "injection": "Second attempt that worked better",
                "asr": 0.8,
                "successful": True,
            },
        ]
        feedback = agent._build_feedback_context(history)

        assert "Iteration 0" in feedback
        assert "Iteration 1" in feedback
        assert "ASR=20.0%" in feedback
        assert "ASR=80.0%" in feedback
        assert "✓ SUCCESS" in feedback
        assert "✗ FAILED" in feedback
        assert "Best ASR so far" in feedback


class TestIntegration:
    """Integration tests for the full RL pipeline."""

    def test_variant_creation_and_selection_pipeline(
        self, sample_injections, sample_variants, sample_eval_data
    ):
        # Create variants
        variant_injections = create_variant_injections(
            sample_injections, sample_variants, iteration=0
        )
        assert len(variant_injections) == 5

        # Compute ASR
        asr = compute_asr(sample_eval_data)
        assert 0 <= asr <= 1

        # Select best
        best = select_best_variants(sample_eval_data, sample_variants, top_k=1)
        assert len(best) > 0
        assert all(isinstance(v, str) for v in best.values())
