# Agent Safety Heuristics Documentation

## Overview

This document describes the comprehensive safety heuristics system implemented in the Cortex-R Agent to ensure secure, reliable, and controlled execution.

## Architecture

The heuristics system is implemented in `modules/heuristics.py` and integrated at multiple checkpoints:

1. **User Input** - Validates queries before processing (`agent.py`)
2. **Plan Generation** - Validates generated code before execution (`modules/action.py`)
3. **Tool Calls** - Validates each tool invocation (`modules/action.py`)

## Heuristics Catalog

### 1. URL Validation ✅

**Purpose**: Prevent access to dangerous or malformed URLs

**Checks**:
- Valid URL format (http/https only)
- Domain/host present
- Blocks localhost and private IPs (SSRF prevention)
- Blocks private IP ranges (192.168.*, 10.*, 172.16.*)

**Example**:
```python
validator.validate_url("http://localhost:8080")  # ❌ Blocked
validator.validate_url("https://example.com")    # ✅ Allowed
```

**Error Messages**:
- "Invalid URL scheme: ftp. Only http/https allowed."
- "Access to localhost is blocked for security reasons"
- "Access to private IP range is blocked"

---

### 2. JSON Validation ✅

**Purpose**: Ensure JSON inputs are well-formed and not excessively nested

**Checks**:
- Valid JSON syntax
- Maximum nesting depth (default: 10 levels)
- Prevents deeply nested structures that could cause stack overflow

**Configuration**:
```yaml
json:
  max_depth: 10
```

**Example**:
```python
validator.validate_json_input('{"a": {"b": {"c": 1}}}')  # ✅ Valid
validator.validate_json_input('{"a": "invalid}')         # ❌ Invalid JSON
```

---

### 3. Input Length Validation ✅

**Purpose**: Prevent memory exhaustion from extremely long inputs

**Checks**:
- Maximum input length (default: 50,000 characters)
- Applied to user input, tool arguments, generated code

**Configuration**:
```yaml
input:
  max_length: 50000
```

**Error Messages**:
- "Input too long: 75000 chars (max: 50000)"

---

### 4. ASCII/Unicode Validation ✅

**Purpose**: Detect potentially malicious Unicode characters

**Checks**:
- Suspicious Unicode characters:
  - Zero-width spaces (\u200B, \u200C, \u200D)
  - Directional overrides (\u202A-\u202E)
  - Zero-width no-break space (\uFEFF)
- Optional strict ASCII-only mode

**Configuration**:
```yaml
input:
  allow_non_ascii: true
  strict_ascii: false
```

**Example**:
```python
# Detects hidden characters that could bypass filters
validator.validate_ascii_content("Hello\u200BWorld")  # ❌ Suspicious
```

---

### 5. Rate Limiting / DDoS Prevention ✅

**Purpose**: Prevent agent from overwhelming external services

**Checks**:
- Maximum calls per domain within time window
- Default: 5 calls per domain per 60 seconds
- Tracks by domain, not full URL

**Configuration**:
```yaml
network:
  max_url_calls_per_domain: 5
  url_call_window_seconds: 60
```

**Error Messages**:
- "Rate limit exceeded for example.com: 5 calls in 60s (max: 5)"

**Example**:
```python
# First 5 calls to example.com: ✅ Allowed
# 6th call within 60s: ❌ Blocked
```

---

### 6. Request Timeout ✅

**Purpose**: Prevent hanging on unresponsive services

**Checks**:
- Configurable timeout for network requests
- Default: 10 seconds
- Applied to all HTTP calls

**Configuration**:
```yaml
network:
  request_timeout_seconds: 10
```

**Usage**:
```python
result = await validator.execute_with_timeout(
    some_network_call(),
    timeout=10
)
```

**Error Messages**:
- "Operation exceeded 10s timeout"
- "Tool call to 'fetch_url' timed out after 10s"

---

### 7. File Input Limits ✅

**Purpose**: Prevent excessive file operations and dangerous path access

**Checks**:
- Maximum files per operation (default: 3)
- Blocked system directories:
  - Linux: `/etc/`, `/sys/`, `/proc/`, `/dev/`, `/boot/`, `/var/`, `/usr/bin/`
  - Windows: `C:\Windows\`, `C:\Program Files\`

**Configuration**:
```yaml
files:
  max_files_per_call: 3
  blocked_paths:
    - "/etc/"
    - "C:\\Windows\\"
```

**Error Messages**:
- "Too many files: 5 (max: 3)"
- "Access to /etc/ is blocked for security"

---

### 8. Dangerous Command Detection ✅

**Purpose**: Prevent execution of system-destructive commands

**Checks**:
- Blocked command patterns:
  - `rm -rf` / `rm -fr`
  - `rmdir /s` / `del /f`
  - `format`, `mkfs` (filesystem operations)
  - `dd if=/dev/zero` (device writes)
  - `:(){:|:&};:` (fork bomb)
  - `> /dev/sda` (device overwrites)
  - `chmod -R 777 /`, `chown -R` (permission changes)

**Configuration**:
```yaml
commands:
  blocked_commands:
    - "rm -rf"
    - "format"
    - ":(){:|:&};:"
```

**Error Messages**:
- "Dangerous command detected: 'rm -rf'"
- "Dangerous command pattern detected"

**Example**:
```python
validator.validate_command_safety("ls -la")        # ✅ Safe
validator.validate_command_safety("rm -rf /")      # ❌ Dangerous
```

---

### 9. Tool Registry Validation ✅

**Purpose**: Ensure only registered tools are called

**Checks**:
- Tool name exists in tool registry
- Prevents typos and unauthorized tool usage

**Configuration**:
```yaml
tools:
  enforce_registry_check: true
```

**Error Messages**:
- "Tool 'unknown_tool' not found in registry. Available tools: add, subtract, multiply..."

**Example**:
```python
available_tools = ["add", "subtract", "multiply"]
validator.validate_tool_exists("add", available_tools)      # ✅ Valid
validator.validate_tool_exists("hack_system", available_tools)  # ❌ Invalid
```

---

### 10. Plan/Code Safety Validation ✅

**Purpose**: Validate generated solve() code before execution

**Checks**:
- Code length within limits
- No dangerous imports (subprocess, os.system, eval, exec)
- No dangerous operations
- Exceptions: `json` and `re` imports are allowed

**Configuration**:
```yaml
plan:
  max_length: 10000
  max_tool_calls: 5
```

**Error Messages**:
- "Plan too long: exceeds 10000 characters"
- "Dangerous operation 'eval' detected in plan"

---

## Additional Heuristics

### 11. Recursion Depth Limit ✅

**Purpose**: Prevent infinite recursion

**Check**: Maximum recursion depth (default: 10)

```python
validator.validate_recursion_depth(current_depth=5, max_depth=10)  # ✅ OK
```

---

### 12. Memory Usage Validation ✅

**Purpose**: Prevent memory exhaustion

**Check**: Maximum data size (default: 100MB)

```python
validator.validate_memory_usage(data_size_bytes=50_000_000, max_size_mb=100)  # ✅ OK
```

---

### 13. API Key Exposure Detection ✅

**Purpose**: Prevent accidental leakage of secrets

**Checks**:
- Common API key patterns
- Secret key patterns
- Password patterns
- Stripe-like keys (sk_*, pk_*)
- Google API keys (AIza...)

**Error Messages**:
- "Potential API key or secret detected in input. Please use environment variables."

**Example**:
```python
validator.validate_api_key_exposure("My api_key is sk_test_12345...")  # ❌ Exposed
```

---

### 14. SQL Injection Detection ✅

**Purpose**: Detect basic SQL injection attempts

**Checks**:
- `' OR '1'='1` patterns
- `DROP TABLE` statements
- `UNION SELECT` attacks
- SQL comments (`--`)

**Example**:
```python
validator.validate_sql_injection("SELECT * FROM users WHERE id=1")  # ✅ Safe
validator.validate_sql_injection("' OR '1'='1")                     # ❌ Injection
```

---

## Integration Points

### 1. Agent Entry Point (`agent.py`)

```python
# Validates user input before processing
validator = get_validator()
is_valid, error = validator.validate_input_length(user_input)
is_valid, error = validator.validate_ascii_content(user_input)
is_valid, error = validator.validate_api_key_exposure(user_input)
```

### 2. Action Module (`modules/action.py`)

```python
# Validates generated plan
is_safe, error = validator.validate_generated_plan(code)

# Validates each tool call
is_valid, errors = await validator.validate_tool_call(
    tool_name, tool_args, available_tools
)

# Applies timeout
result = await validator.execute_with_timeout(
    dispatcher.call_tool(tool_name, input_dict),
    timeout=10
)
```

### 3. Session Management

```python
# Reset validator for new sessions
reset_validator()

# Get validation report
report = validator.get_validation_report()
```

---

## Configuration

All heuristics can be configured via `config/heuristics.yaml`:

```yaml
input:
  max_length: 50000
  allow_non_ascii: true

network:
  request_timeout_seconds: 10
  max_url_calls_per_domain: 5
  
files:
  max_files_per_call: 3
  
commands:
  blocked_commands: [...]
  
plan:
  max_length: 10000
  max_tool_calls: 5
```

---

## Usage Examples

### Basic Validation

```python
from modules.heuristics import get_validator

validator = get_validator()

# Validate URL
is_valid, error = validator.validate_url("https://example.com")
if not is_valid:
    print(f"URL Error: {error}")

# Validate command
is_safe, error = validator.validate_command_safety("ls -la")
if not is_safe:
    print(f"Command Error: {error}")
```

### Tool Call Validation

```python
tool_name = "fetch_url"
tool_args = {"input": {"url": "https://example.com"}}
available_tools = ["fetch_url", "search_docs"]

is_valid, errors = await validator.validate_tool_call(
    tool_name, tool_args, available_tools
)

if not is_valid:
    for error in errors:
        print(f"Validation Error: {error}")
```

### With Timeout

```python
try:
    result = await validator.execute_with_timeout(
        fetch_data_from_api(),
        timeout=10
    )
except asyncio.TimeoutError:
    print("Operation timed out")
```

---

## Monitoring & Reporting

Get current validation state:

```python
report = validator.get_validation_report()
print(report)

# Output:
# {
#   "session_duration_seconds": 150.5,
#   "url_calls_by_domain": {
#     "example.com": 3,
#     "api.github.com": 2
#   },
#   "total_tool_calls": 12,
#   "config": {...}
# }
```

---

## Error Handling

All validation methods return `(is_valid, error_message)` tuples:

```python
is_valid, error = validator.validate_url(url)
if not is_valid:
    log("error", f"Validation failed: {error}")
    # Handle error appropriately
```

For async operations, `HeuristicViolation` exceptions may be raised:

```python
try:
    result = await validator.execute_with_timeout(operation)
except HeuristicViolation as e:
    print(f"Rule: {e.rule}, Message: {e.message}, Severity: {e.severity}")
```

---

## Best Practices

1. **Always validate at boundaries**: User input, tool calls, external data
2. **Use appropriate severity**: Not all violations are fatal errors
3. **Log all violations**: Helps with debugging and security auditing
4. **Configure for your use case**: Adjust limits based on requirements
5. **Reset validator between sessions**: Prevents state leakage
6. **Monitor the report**: Track resource usage and rate limiting

---

## Security Considerations

1. **Defense in Depth**: Multiple layers of validation
2. **Fail Secure**: On validation failure, deny operation
3. **Least Privilege**: Block by default, allow explicitly
4. **Input Sanitization**: Never trust user input
5. **Rate Limiting**: Protect external services
6. **Timeout All Network Ops**: Prevent hanging
7. **Log Security Events**: Track attempted violations

---

## Future Enhancements

Potential additional heuristics:

- **Path Traversal Detection** (`../../etc/passwd`)
- **XSS/HTML Injection Detection**
- **Credit Card Number Detection**
- **Email Address Exposure**
- **IP Geolocation Blocking** (block certain countries)
- **Time-based Rate Limiting** (per session, not just per domain)
- **Resource Quota Management** (total API calls per session)
- **Anomaly Detection** (unusual patterns in tool usage)
- **Content Type Validation** (verify response matches expected type)
- **Certificate Pinning** (for critical domains)

---

## Testing

To test heuristics:

```python
from modules.heuristics import HeuristicValidator

validator = HeuristicValidator()

# Test URL validation
assert validator.validate_url("http://localhost")[0] == False
assert validator.validate_url("https://example.com")[0] == True

# Test command safety
assert validator.validate_command_safety("rm -rf /")[0] == False
assert validator.validate_command_safety("ls -la")[0] == True

# Test rate limiting
for i in range(6):
    valid, _ = validator.check_url_rate_limit("https://example.com/page")
    print(f"Call {i+1}: {'✅' if valid else '❌'}")
```

---

## Troubleshooting

### Issue: Rate limit false positives

**Solution**: Increase `url_call_window_seconds` or `max_url_calls_per_domain` in config

### Issue: Legitimate commands blocked

**Solution**: Review `blocked_commands` list and remove if safe for your use case

### Issue: Timeouts on slow APIs

**Solution**: Increase `request_timeout_seconds` in config

### Issue: Unicode characters in user queries flagged

**Solution**: Set `allow_non_ascii: true` and `strict_ascii: false`

---

## Contributing

When adding new heuristics:

1. Add validation method to `HeuristicValidator` class
2. Add configuration to `config/heuristics.yaml`
3. Integrate at appropriate checkpoint (input/plan/tool)
4. Document in this file with examples
5. Add tests
6. Update error messages for clarity

---

## License

Part of the Cortex-R Agent system.

