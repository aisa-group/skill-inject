"""
Test runner for instruction unit tests.

This module provides utilities to run instruction-specific tests against sandbox results.
Supports both regular instructions (instructions.json) and obvious injections (obvious_injections.json).
"""

import importlib
import sys
from pathlib import Path
from typing import Dict, Tuple, Optional, Callable


# Discover tests from filenames so adding a detector cannot leave the runner registry stale.
INSTRUCTION_TEST_MODULES = {
    int(path.stem.removeprefix("test_instruction_")): path.stem
    for path in Path(__file__).parent.glob("test_instruction_*.py")
}
OBVIOUS_INJECTION_TEST_MODULES = {
    int(path.stem.removeprefix("test_obvious_")): path.stem
    for path in (Path(__file__).parent / "obvious").glob("test_obvious_*.py")
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
        module = importlib.import_module(module_name)

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
        module = importlib.import_module(f"obvious.{module_name}")

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
        module = importlib.import_module(module_name)
        
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
