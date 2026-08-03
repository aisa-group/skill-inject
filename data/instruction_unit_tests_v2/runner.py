"""
Test runner for instruction unit tests.

This module provides utilities to run instruction-specific tests against sandbox results.
Supports both regular instructions (instructions.json) and obvious injections (obvious_injections.json).
"""

import importlib
import sys
from pathlib import Path
from typing import Dict, Tuple, Optional, Callable


# Map instruction IDs to their test modules
INSTRUCTION_TEST_MODULES = {
    1: "test_instruction_1",
    2: "test_instruction_2",
    3: "test_instruction_3",
    4: "test_instruction_4",
    5: "test_instruction_5",
    6: "test_instruction_6",
    7: "test_instruction_7",
    8: "test_instruction_8",
    9: "test_instruction_9",
    10: "test_instruction_10",
    11: "test_instruction_11",
    12: "test_instruction_12",
    13: "test_instruction_13",
    14: "test_instruction_14",
    15: "test_instruction_15",
    25: "test_instruction_25",
    26: "test_instruction_26",
}

# Map obvious injection IDs to their test modules
OBVIOUS_INJECTION_TEST_MODULES = {
    1: "test_obvious_1",
    2: "test_obvious_2",
    3: "test_obvious_3",
    4: "test_obvious_4",
    5: "test_obvious_5",
    7: "test_obvious_7",
    8: "test_obvious_8",
    9: "test_obvious_9",
    10: "test_obvious_10",
    11: "test_obvious_11",
    14: "test_obvious_14",
    15: "test_obvious_15",
    16: "test_obvious_16",
    17: "test_obvious_17",
    18: "test_obvious_18",
    19: "test_obvious_19",
    20: "test_obvious_20",
    22: "test_obvious_22",
    23: "test_obvious_23",
}


def get_test_function(instruction_id: int) -> Optional[Callable[[Path], Tuple[bool, str]]]:
    """
    Get the test function for a given instruction ID.

    Args:
        instruction_id: The instruction ID to get the test for

    Returns:
        The test function, or None if no test exists for this instruction
    """
    if instruction_id not in INSTRUCTION_TEST_MODULES:
        return None

    module_name = INSTRUCTION_TEST_MODULES[instruction_id]

    try:
        # Import the test module
        module = importlib.import_module(f".{module_name}", package="instruction_unit_tests")

        # Get the test function
        test_func = getattr(module, f"test_instruction_{instruction_id}", None)
        return test_func
    except ImportError as e:
        print(f"Warning: Could not import test module for instruction {instruction_id}: {e}")
        return None


def get_obvious_test_function(injection_id: int) -> Optional[Callable[[Path], Tuple[bool, str]]]:
    """
    Get the test function for a given obvious injection ID.

    Args:
        injection_id: The obvious injection ID to get the test for

    Returns:
        The test function, or None if no test exists for this injection
    """
    if injection_id not in OBVIOUS_INJECTION_TEST_MODULES:
        return None

    module_name = OBVIOUS_INJECTION_TEST_MODULES[injection_id]

    try:
        # Import the test module from the obvious subpackage
        module = importlib.import_module(f".obvious.{module_name}", package="instruction_unit_tests")

        # Get the test function
        test_func = getattr(module, f"test_obvious_{injection_id}", None)
        return test_func
    except ImportError as e:
        print(f"Warning: Could not import test module for obvious injection {injection_id}: {e}")
        return None


def run_test(instruction_id: int, sandbox_dir: Path) -> Tuple[bool, str]:
    """
    Run the test for a specific instruction against a sandbox directory.

    Args:
        instruction_id: The instruction ID to test
        sandbox_dir: Path to the sandbox directory

    Returns:
        Tuple of (attack_succeeded: bool, reason: str)
    """
    test_func = get_test_function(instruction_id)

    if test_func is None:
        return False, f"No test available for instruction {instruction_id}"

    try:
        return test_func(sandbox_dir)
    except Exception as e:
        return False, f"Test error: {str(e)}"


def run_obvious_test(injection_id: int, sandbox_dir: Path) -> Tuple[bool, str]:
    """
    Run the test for a specific obvious injection against a sandbox directory.

    Args:
        injection_id: The obvious injection ID to test
        sandbox_dir: Path to the sandbox directory

    Returns:
        Tuple of (attack_succeeded: bool, reason: str)
    """
    test_func = get_obvious_test_function(injection_id)

    if test_func is None:
        return False, f"No test available for obvious injection {injection_id}"

    try:
        return test_func(sandbox_dir)
    except Exception as e:
        return False, f"Test error: {str(e)}"


def get_test_metadata(instruction_id: int) -> Optional[Dict]:
    """
    Get metadata about a test (title, description, attack type).
    
    Args:
        instruction_id: The instruction ID
        
    Returns:
        Dictionary with metadata, or None if no test exists
    """
    if instruction_id not in INSTRUCTION_TEST_MODULES:
        return None
    
    module_name = INSTRUCTION_TEST_MODULES[instruction_id]
    
    try:
        module = importlib.import_module(f".{module_name}", package="instruction_unit_tests")
        
        return {
            "instruction_id": getattr(module, "INSTRUCTION_ID", instruction_id),
            "title": getattr(module, "INSTRUCTION_TITLE", f"Instruction {instruction_id}"),
            "description": getattr(module, "TEST_DESCRIPTION", "No description"),
            "attack_type": getattr(module, "ATTACK_TYPE", "unknown"),
        }
    except ImportError:
        return None


def list_available_tests() -> Dict[int, Dict]:
    """
    List all available instruction tests with their metadata.
    
    Returns:
        Dictionary mapping instruction IDs to their metadata
    """
    available = {}
    for inst_id in INSTRUCTION_TEST_MODULES:
        metadata = get_test_metadata(inst_id)
        if metadata:
            available[inst_id] = metadata
    return available


if __name__ == "__main__":
    # Example usage / self-test
    print("Available instruction tests:")
    print("-" * 60)
    
    for inst_id, metadata in list_available_tests().items():
        print(f"Instruction {inst_id}: {metadata['title']}")
        print(f"  Type: {metadata['attack_type']}")
        print(f"  Test: {metadata['description']}")
        print()
