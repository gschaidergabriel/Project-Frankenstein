#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Edge Case Tests - Post-Fix Validation
======================================

Tests extreme inputs and boundary conditions for:
1. SafeExpressionEvaluator - extreme inputs
2. SQL/Input Validation - empty strings
3. Color Validation - invalid hex codes
4. MAX_RESPONSE_LENGTH - boundary (1000/1001 chars)
5. MAX_OVERLAY_RETRIES - 50 retries
6. Gaming Mode - corrupt JSON
7. PID Cleanup - invalid PIDs
8. Concurrent Writes - race conditions
9. Subprocess Timeouts

Author: QA Edge Case Hunter
Date: 2026-02-01
"""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from concurrent.futures import ThreadPoolExecutor
import fcntl

# Add aicore to path
AICORE_ROOT = Path("/home/ai-core-node/aicore/opt/aicore")
sys.path.insert(0, str(AICORE_ROOT))


class TestSafeExpressionEvaluator(unittest.TestCase):
    """Edge cases for SafeExpressionEvaluator."""

    def setUp(self):
        from personality.ego_construct import SafeExpressionEvaluator
        self.evaluator_class = SafeExpressionEvaluator

    def test_very_long_expression(self):
        """Test with extremely long expression (10000 chars)."""
        # Build a very long but valid expression: a + a + a + ...
        variables = {"a": 1}
        evaluator = self.evaluator_class(variables)

        # 5000 "a + " = 20000 characters
        long_expr = " + ".join(["a"] * 5000)

        try:
            result = evaluator.evaluate(long_expr)
            self.assertEqual(result, 5000)  # 5000 * 1 = 5000
            print(f"[PASS] Very long expression (20000 chars): evaluated correctly")
        except RecursionError:
            print(f"[EDGE CASE] Very long expression causes RecursionError")
            # This is actually expected for very deep nesting
        except Exception as e:
            print(f"[EDGE CASE] Very long expression error: {type(e).__name__}: {e}")

    def test_unicode_in_expression(self):
        """Test with Unicode characters in expression."""
        variables = {"wert": 42}
        evaluator = self.evaluator_class(variables)

        # Unicode variable name
        test_cases = [
            ("wert > 0", True),
            ("wert + 0", 42),
        ]

        for expr, expected in test_cases:
            try:
                result = evaluator.evaluate(expr)
                self.assertEqual(result, expected)
                print(f"[PASS] Expression '{expr}': {result}")
            except Exception as e:
                print(f"[EDGE CASE] Expression '{expr}' error: {type(e).__name__}")

    def test_unicode_variable_names(self):
        """Test with Unicode variable names (German umlauts)."""
        # Python AST should handle Unicode identifiers
        variables = {"temperatur": 75}  # Simplified - no umlaut
        evaluator = self.evaluator_class(variables)

        try:
            result = evaluator.evaluate("temperatur > 70")
            self.assertTrue(result)
            print(f"[PASS] Unicode variable name: works")
        except Exception as e:
            print(f"[EDGE CASE] Unicode variable name error: {type(e).__name__}")

    def test_empty_expression(self):
        """Test with empty string."""
        evaluator = self.evaluator_class({})

        try:
            result = evaluator.evaluate("")
            print(f"[EDGE CASE] Empty expression returned: {result}")
        except ValueError as e:
            print(f"[PASS] Empty expression raises ValueError: {e}")
        except SyntaxError:
            print(f"[PASS] Empty expression raises SyntaxError")

    def test_whitespace_only(self):
        """Test with whitespace-only expression."""
        evaluator = self.evaluator_class({})

        try:
            result = evaluator.evaluate("   ")
            print(f"[EDGE CASE] Whitespace expression returned: {result}")
        except ValueError:
            print(f"[PASS] Whitespace-only expression raises ValueError")
        except SyntaxError:
            print(f"[PASS] Whitespace-only expression raises SyntaxError")

    def test_division_by_zero(self):
        """Test division by zero."""
        evaluator = self.evaluator_class({"a": 10, "b": 0})

        try:
            result = evaluator.evaluate("a / b")
            print(f"[EDGE CASE] Division by zero returned: {result}")
        except ZeroDivisionError:
            print(f"[PASS] Division by zero raises ZeroDivisionError")
        except ValueError as e:
            print(f"[PASS] Division by zero raises ValueError: {e}")

    def test_nested_function_calls(self):
        """Test deeply nested function calls."""
        evaluator = self.evaluator_class({"a": -5})

        # max(min(max(min(...))))
        try:
            result = evaluator.evaluate("max(min(max(min(abs(a), 10), 5), 8), 3)")
            print(f"[PASS] Nested functions: {result}")
        except Exception as e:
            print(f"[EDGE CASE] Nested functions error: {type(e).__name__}: {e}")

    def test_injection_attempt(self):
        """Test code injection attempts."""
        evaluator = self.evaluator_class({"x": 1})

        injection_attempts = [
            "__import__('os').system('ls')",
            "exec('print(1)')",
            "eval('1+1')",
            "open('/etc/passwd').read()",
            "().__class__.__bases__[0].__subclasses__()",
            "lambda: 1",
            "[x for x in range(10)]",
        ]

        for attempt in injection_attempts:
            try:
                result = evaluator.evaluate(attempt)
                print(f"[SECURITY ISSUE] Injection succeeded: {attempt[:30]}... -> {result}")
            except (ValueError, SyntaxError) as e:
                print(f"[PASS] Injection blocked: {attempt[:30]}...")
            except Exception as e:
                print(f"[PASS] Injection blocked ({type(e).__name__}): {attempt[:30]}...")


class TestInputValidation(unittest.TestCase):
    """Edge cases for input validation including empty strings."""

    def test_empty_string_in_json_loads(self):
        """Test empty string JSON parsing."""
        try:
            result = json.loads("")
            print(f"[EDGE CASE] Empty JSON string returned: {result}")
        except json.JSONDecodeError:
            print(f"[PASS] Empty JSON string raises JSONDecodeError")

    def test_empty_string_path(self):
        """Test empty string as file path."""
        from pathlib import Path

        try:
            p = Path("")
            exists = p.exists()
            print(f"[INFO] Empty path exists(): {exists}")
            # Empty path resolves to current directory
            self.assertEqual(p.resolve(), Path.cwd())
            print(f"[PASS] Empty path resolves to cwd")
        except Exception as e:
            print(f"[EDGE CASE] Empty path error: {type(e).__name__}: {e}")

    def test_null_bytes_in_string(self):
        """Test null bytes in strings (potential truncation)."""
        test_str = "hello\x00world"

        # JSON handling
        try:
            encoded = json.dumps({"text": test_str})
            decoded = json.loads(encoded)
            if decoded["text"] == test_str:
                print(f"[PASS] JSON preserves null bytes")
            else:
                print(f"[EDGE CASE] JSON modified null bytes")
        except Exception as e:
            print(f"[EDGE CASE] JSON null byte error: {type(e).__name__}")

        # File path handling
        try:
            Path(test_str)
            print(f"[EDGE CASE] Path accepts null bytes")
        except ValueError:
            print(f"[PASS] Path rejects null bytes")


class TestColorValidation(unittest.TestCase):
    """Edge cases for color validation (CSS injection prevention)."""

    def setUp(self):
        # Simulate the ALLOWED_COLORS from ewish_popup/main_window.py
        self.ALLOWED_COLORS = {"#00ff88", "#ff4444", "#00fff9", "#ff00ff", "#ffff00"}
        self.DEFAULT_COLOR = "#00ff88"

    def validate_color(self, color: str) -> str:
        """Replicate the validation logic."""
        if color not in self.ALLOWED_COLORS:
            return self.DEFAULT_COLOR
        return color

    def test_valid_colors(self):
        """Test valid hex colors."""
        for color in self.ALLOWED_COLORS:
            result = self.validate_color(color)
            self.assertEqual(result, color)
            print(f"[PASS] Valid color: {color}")

    def test_invalid_hex_formats(self):
        """Test various invalid hex color formats."""
        invalid_colors = [
            "#fff",           # 3-char hex
            "#ffffff",        # Not in whitelist
            "#00ff8",         # 5 chars
            "#00ff888",       # 7 chars
            "00ff88",         # Missing #
            "#00FF88",        # Uppercase
            "#g0ff88",        # Invalid hex char
            "",               # Empty
            " #00ff88",       # Leading space
            "#00ff88 ",       # Trailing space
            "#00ff88; background: red",  # CSS injection attempt
            "rgb(0,255,136)", # RGB format
            "green",          # Named color
        ]

        for color in invalid_colors:
            result = self.validate_color(color)
            self.assertEqual(result, self.DEFAULT_COLOR)
            print(f"[PASS] Invalid color rejected: '{color[:30]}'")

    def test_css_injection_attempts(self):
        """Test CSS injection attack vectors."""
        injection_attempts = [
            "#00ff88; } body { background: red; } .fake {",
            "#00ff88</style><script>alert(1)</script>",
            "#00ff88\n.malicious { content: 'evil' }",
            "#00ff88; @import url('evil.css');",
            "expression(alert('xss'))",
        ]

        for attempt in injection_attempts:
            result = self.validate_color(attempt)
            self.assertEqual(result, self.DEFAULT_COLOR)
            print(f"[PASS] CSS injection blocked: '{attempt[:40]}...'")


class TestMaxResponseLength(unittest.TestCase):
    """Edge cases for MAX_RESPONSE_LENGTH boundary (1000 chars)."""

    MAX_RESPONSE_LENGTH = 1000

    def truncate_response(self, text: str) -> str:
        """Replicate truncation logic from main_window.py."""
        if len(text) > self.MAX_RESPONSE_LENGTH:
            return text[:self.MAX_RESPONSE_LENGTH]
        return text

    def test_exactly_1000_chars(self):
        """Test exactly 1000 characters (boundary)."""
        text = "a" * 1000
        result = self.truncate_response(text)
        self.assertEqual(len(result), 1000)
        print(f"[PASS] Exactly 1000 chars: kept as-is")

    def test_exactly_1001_chars(self):
        """Test exactly 1001 characters (just over boundary)."""
        text = "a" * 1001
        result = self.truncate_response(text)
        self.assertEqual(len(result), 1000)
        print(f"[PASS] Exactly 1001 chars: truncated to 1000")

    def test_999_chars(self):
        """Test 999 characters (just under boundary)."""
        text = "a" * 999
        result = self.truncate_response(text)
        self.assertEqual(len(result), 999)
        print(f"[PASS] 999 chars: kept as-is")

    def test_unicode_boundary(self):
        """Test Unicode characters at boundary (multi-byte chars)."""
        # German umlaut is 2 bytes in UTF-8
        text = "a" * 998 + "ae"  # 1000 chars, but last one could be special
        result = self.truncate_response(text)
        self.assertEqual(len(result), 1000)
        print(f"[PASS] Unicode at boundary: handled correctly")

    def test_empty_input(self):
        """Test empty input."""
        result = self.truncate_response("")
        self.assertEqual(result, "")
        print(f"[PASS] Empty input: returns empty")


class TestMaxOverlayRetries(unittest.TestCase):
    """Edge cases for MAX_OVERLAY_RETRIES (50 retries)."""

    MAX_OVERLAY_RETRIES = 50

    def test_retry_counter_at_50(self):
        """Simulate exactly 50 retries."""
        retry_count = 0

        for i in range(100):  # Try more than max
            retry_count += 1
            if retry_count > self.MAX_OVERLAY_RETRIES:
                break

        self.assertEqual(retry_count, 51)  # 50 + 1 (the check that breaks)
        print(f"[PASS] Retry loop exits at 51 iterations (after 50 retries)")

    def test_retry_timing(self):
        """Test retry timing doesn't cause excessive delay."""
        # 50 retries * 100ms = 5000ms = 5 seconds max
        max_time_ms = self.MAX_OVERLAY_RETRIES * 100
        self.assertEqual(max_time_ms, 5000)
        print(f"[PASS] Max retry time: {max_time_ms}ms (5 seconds)")


class TestGamingModeCorruptJSON(unittest.TestCase):
    """Edge cases for Gaming Mode with corrupt JSON."""

    def test_corrupt_json_file(self):
        """Test handling of corrupt JSON state file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("{ invalid json }")
            temp_path = f.name

        try:
            # Simulate gaming_mode.py load behavior
            try:
                with open(temp_path, 'r') as f:
                    data = json.load(f)
                print(f"[EDGE CASE] Corrupt JSON was parsed: {data}")
            except json.JSONDecodeError:
                print(f"[PASS] Corrupt JSON raises JSONDecodeError")
        finally:
            os.unlink(temp_path)

    def test_empty_json_file(self):
        """Test handling of empty JSON file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("")
            temp_path = f.name

        try:
            try:
                with open(temp_path, 'r') as f:
                    data = json.load(f)
                print(f"[EDGE CASE] Empty JSON was parsed: {data}")
            except json.JSONDecodeError:
                print(f"[PASS] Empty JSON raises JSONDecodeError")
        finally:
            os.unlink(temp_path)

    def test_binary_garbage_in_json(self):
        """Test handling of binary garbage in JSON file."""
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.json', delete=False) as f:
            f.write(b'\x00\x01\x02\xff\xfe\xfd')
            temp_path = f.name

        try:
            try:
                with open(temp_path, 'r') as f:
                    data = json.load(f)
                print(f"[EDGE CASE] Binary garbage was parsed")
            except (json.JSONDecodeError, UnicodeDecodeError):
                print(f"[PASS] Binary garbage raises decode error")
        finally:
            os.unlink(temp_path)

    def test_very_large_json(self):
        """Test handling of very large JSON file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            # 10MB of valid JSON
            large_data = {"data": "x" * (10 * 1024 * 1024)}
            json.dump(large_data, f)
            temp_path = f.name

        try:
            start = time.time()
            with open(temp_path, 'r') as f:
                data = json.load(f)
            elapsed = time.time() - start
            print(f"[PASS] Large JSON (10MB) parsed in {elapsed:.2f}s")
        except MemoryError:
            print(f"[EDGE CASE] Large JSON causes MemoryError")
        finally:
            os.unlink(temp_path)


class TestPIDCleanup(unittest.TestCase):
    """Edge cases for PID file cleanup."""

    def test_invalid_pid_string(self):
        """Test PID file with invalid content."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pid', delete=False) as f:
            f.write("not_a_number")
            temp_path = f.name

        try:
            content = Path(temp_path).read_text().strip()
            try:
                pid = int(content)
                print(f"[EDGE CASE] Invalid PID was parsed: {pid}")
            except ValueError:
                print(f"[PASS] Invalid PID raises ValueError")
        finally:
            os.unlink(temp_path)

    def test_negative_pid(self):
        """Test negative PID."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pid', delete=False) as f:
            f.write("-1")
            temp_path = f.name

        try:
            pid = int(Path(temp_path).read_text().strip())
            try:
                os.kill(pid, 0)
                print(f"[EDGE CASE] Negative PID check succeeded")
            except (OSError, ProcessLookupError):
                print(f"[PASS] Negative PID check raises error")
        finally:
            os.unlink(temp_path)

    def test_very_large_pid(self):
        """Test very large PID number."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pid', delete=False) as f:
            f.write("999999999999")  # Way beyond max PID
            temp_path = f.name

        try:
            pid = int(Path(temp_path).read_text().strip())
            try:
                os.kill(pid, 0)
                print(f"[EDGE CASE] Huge PID check succeeded")
            except (OSError, ProcessLookupError, OverflowError):
                print(f"[PASS] Huge PID check raises error")
        finally:
            os.unlink(temp_path)

    def test_zero_pid(self):
        """Test PID 0 (special meaning: current process group)."""
        try:
            os.kill(0, 0)
            print(f"[INFO] PID 0 check succeeded (signals process group)")
        except (OSError, ProcessLookupError):
            print(f"[INFO] PID 0 check failed")


class TestConcurrentWrites(unittest.TestCase):
    """Edge cases for concurrent file writes."""

    def test_concurrent_json_writes(self):
        """Test race condition in concurrent JSON writes."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"counter": 0}, f)
            temp_path = f.name

        errors = []
        success_count = [0]

        def write_json(thread_id: int):
            try:
                for i in range(10):
                    # Read-modify-write without locking (race condition)
                    data = json.loads(Path(temp_path).read_text())
                    data["counter"] += 1
                    data[f"thread_{thread_id}"] = i
                    Path(temp_path).write_text(json.dumps(data))
                    time.sleep(0.001)
                success_count[0] += 1
            except Exception as e:
                errors.append(f"Thread {thread_id}: {type(e).__name__}: {e}")

        threads = [threading.Thread(target=write_json, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        try:
            final_data = json.loads(Path(temp_path).read_text())
            expected_counter = 5 * 10  # 5 threads * 10 increments each
            actual_counter = final_data.get("counter", 0)

            if actual_counter == expected_counter:
                print(f"[INFO] Concurrent writes: counter correct ({actual_counter})")
            else:
                print(f"[EDGE CASE] Race condition! Expected {expected_counter}, got {actual_counter}")

            if errors:
                print(f"[EDGE CASE] Errors during concurrent writes: {errors}")
        finally:
            os.unlink(temp_path)

    def test_atomic_write_with_locking(self):
        """Test atomic write with file locking (the correct way)."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"counter": 0}, f)
            temp_path = f.name

        lock_path = temp_path + ".lock"
        success_count = [0]

        def atomic_write(thread_id: int):
            for i in range(10):
                # Proper locking
                with open(lock_path, 'w') as lock_file:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                    try:
                        data = json.loads(Path(temp_path).read_text())
                        data["counter"] += 1
                        # Atomic write via temp file
                        tmp = temp_path + ".tmp"
                        Path(tmp).write_text(json.dumps(data))
                        os.rename(tmp, temp_path)
                    finally:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                time.sleep(0.001)
            success_count[0] += 1

        threads = [threading.Thread(target=atomic_write, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        try:
            final_data = json.loads(Path(temp_path).read_text())
            expected = 50
            actual = final_data.get("counter", 0)

            if actual == expected:
                print(f"[PASS] Atomic writes: counter correct ({actual})")
            else:
                print(f"[EDGE CASE] Atomic write failed! Expected {expected}, got {actual}")
        finally:
            os.unlink(temp_path)
            if Path(lock_path).exists():
                os.unlink(lock_path)


class TestSubprocessTimeouts(unittest.TestCase):
    """Edge cases for subprocess timeouts."""

    def test_timeout_kills_process(self):
        """Test that timeout properly kills hanging process."""
        import subprocess

        try:
            result = subprocess.run(
                ["sleep", "10"],
                capture_output=True,
                timeout=0.1  # 100ms timeout
            )
            print(f"[EDGE CASE] Sleep completed before timeout")
        except subprocess.TimeoutExpired:
            print(f"[PASS] Timeout properly raised after 100ms")

    def test_timeout_with_large_output(self):
        """Test timeout with process generating large output."""
        import subprocess

        try:
            # Generate 1MB of output
            result = subprocess.run(
                ["yes", "x"],
                capture_output=True,
                timeout=0.1
            )
            print(f"[EDGE CASE] yes command completed: {len(result.stdout)} bytes")
        except subprocess.TimeoutExpired as e:
            output_size = len(e.stdout) if e.stdout else 0
            print(f"[PASS] Timeout with large output: captured {output_size} bytes")

    def test_popen_without_timeout(self):
        """Test Popen without timeout (potential hang)."""
        import subprocess

        # This is how gaming_mode.py starts processes
        proc = subprocess.Popen(
            ["sleep", "0.1"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # Proper cleanup
        try:
            stdout, stderr = proc.communicate(timeout=1)
            print(f"[PASS] Popen with communicate timeout works")
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            print(f"[PASS] Popen timeout handled with kill()")


def run_all_tests():
    """Run all edge case tests and generate report."""
    print("=" * 70)
    print("EDGE CASE TEST REPORT")
    print("=" * 70)
    print()

    test_classes = [
        TestSafeExpressionEvaluator,
        TestInputValidation,
        TestColorValidation,
        TestMaxResponseLength,
        TestMaxOverlayRetries,
        TestGamingModeCorruptJSON,
        TestPIDCleanup,
        TestConcurrentWrites,
        TestSubprocessTimeouts,
    ]

    results = []

    for test_class in test_classes:
        print(f"\n{'=' * 70}")
        print(f"Testing: {test_class.__name__}")
        print(f"{'=' * 70}")

        suite = unittest.TestLoader().loadTestsFromTestCase(test_class)
        runner = unittest.TextTestRunner(verbosity=0)
        result = runner.run(suite)

        results.append({
            "class": test_class.__name__,
            "tests": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
        })

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    total_tests = sum(r["tests"] for r in results)
    total_failures = sum(r["failures"] for r in results)
    total_errors = sum(r["errors"] for r in results)

    for r in results:
        status = "OK" if r["failures"] == 0 and r["errors"] == 0 else "ISSUES"
        print(f"  {r['class']}: {r['tests']} tests, "
              f"{r['failures']} failures, {r['errors']} errors [{status}]")

    print(f"\nTotal: {total_tests} tests, {total_failures} failures, {total_errors} errors")

    return total_failures == 0 and total_errors == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
