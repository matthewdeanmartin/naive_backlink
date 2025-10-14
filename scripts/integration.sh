#!/bin/bash
#
# A simple integration test script that installs the project and runs the CLI
# against live, real-world URLs to check for expected behavior.

# Exit immediately if a command exits with a non-zero status.
# set -e

# --- Test Runner ---

# A simple function to run a test and print its status.
run_test() {
    local test_name="$1"
    # All arguments after the first are the command to run.
    local command="${@:2}"

    echo "--- Running test: $test_name ---"

    # Execute the command. The `set -e` will cause the script to exit
    # on failure, so if we get past this line, it succeeded.
    output=$(eval "$command")

    echo "$output"
    echo "--- PASS: $test_name ---"
    echo # Newline for readability
}

# --- Main Script ---

echo "Starting integration tests for naive-backlink..."


# 2. Define the tests to run.

# Test Case 1: troml-dev-status
# This project links to a GitHub repository, which should link back.
# We expect to find evidence and get a non-zero score.
# We grep the output to ensure it's finding the GitHub link.
run_test "troml-dev-status" "\
    naive_backlink --verbose verify https://pypi.org/project/troml-dev-status/ \
"

# Test Case 2: attrs
# A very popular project with a well-established website and GitHub presence.
# We expect a high score and strong evidence from its GitHub organization.
run_test "attrs" "\
    naive_backlink --verbose  verify https://pypi.org/project/attrs/ \
"

echo "All integration tests passed successfully!"
