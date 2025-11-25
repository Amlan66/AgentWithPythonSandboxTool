# modules/heuristics.py

"""
Agent Safety Heuristics & Validation System
Provides runtime validation and safety checks for the agent's operations
"""

import re
import json
import time
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse
from collections import defaultdict
from pydantic import BaseModel
import asyncio

# Optional logging fallback
try:
    from agent import log
except ImportError:
    import datetime
    def log(stage: str, msg: str):
        now = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"[{now}] [{stage}] {msg}")


class HeuristicConfig(BaseModel):
    """Configuration for heuristic validators"""
    max_input_length: int = 50000  # 50k characters
    max_json_depth: int = 10
    max_files_per_call: int = 3
    max_url_calls_per_domain: int = 5
    url_call_window_seconds: int = 60
    request_timeout_seconds: int = 10
    allow_non_ascii: bool = True
    blocked_commands: List[str] = [
        "rm -rf", "rm -fr", "rmdir /s", "del /f", "format",
        "dd if=/dev/zero", ":(){:|:&};:", "mkfs", "sudo rm",
        "> /dev/sda", "mv /* ", "chmod -R 777 /", "chown -R"
    ]
    blocked_file_operations: List[str] = [
        "/etc/", "/sys/", "/proc/", "/dev/", "/boot/",
        "C:\\Windows\\", "C:\\Program Files\\", "/var/", "/usr/bin/"
    ]
    max_plan_length: int = 10000  # Max length of generated solve() code


class HeuristicViolation(Exception):
    """Raised when a heuristic check fails"""
    def __init__(self, rule: str, message: str, severity: str = "error"):
        self.rule = rule
        self.message = message
        self.severity = severity  # 'error', 'warning', 'info'
        super().__init__(f"[{severity.upper()}] {rule}: {message}")


class HeuristicValidator:
    """Main validator class for agent safety checks"""
    
    def __init__(self, config: Optional[HeuristicConfig] = None):
        self.config = config or HeuristicConfig()
        self.url_call_tracker: Dict[str, List[float]] = defaultdict(list)
        self.tool_call_tracker: Dict[str, int] = defaultdict(int)
        self.session_start_time = time.time()
        
    # ============================================
    # 1. URL Validation
    # ============================================
    
    def validate_url(self, url: str) -> Tuple[bool, Optional[str]]:
        """
        Check if URL is valid and safe to access
        Returns: (is_valid, error_message)
        """
        if not url or not isinstance(url, str):
            return False, "URL is empty or not a string"
        
        # Basic URL format check
        try:
            parsed = urlparse(url)
            if not parsed.scheme in ['http', 'https']:
                return False, f"Invalid URL scheme: {parsed.scheme}. Only http/https allowed."
            if not parsed.netloc:
                return False, "URL missing domain/host"
        except Exception as e:
            return False, f"Malformed URL: {str(e)}"
        
        # Check for localhost/private IPs (prevent SSRF)
        blocked_hosts = ['localhost', '127.0.0.1', '0.0.0.0', '::1']
        if parsed.hostname in blocked_hosts:
            return False, f"Access to {parsed.hostname} is blocked for security reasons"
        
        # Check for private IP ranges
        if parsed.hostname:
            if (parsed.hostname.startswith('192.168.') or 
                parsed.hostname.startswith('10.') or
                parsed.hostname.startswith('172.16.')):
                return False, f"Access to private IP range is blocked"
        
        return True, None
    
    # ============================================
    # 2. JSON Validation
    # ============================================
    
    def validate_json_input(self, json_str: str, max_depth: Optional[int] = None) -> Tuple[bool, Optional[str], Optional[dict]]:
        """
        Validate JSON structure and depth
        Returns: (is_valid, error_message, parsed_json)
        """
        max_depth = max_depth or self.config.max_json_depth
        
        if not json_str or not isinstance(json_str, str):
            return False, "JSON input is empty or not a string", None
        
        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError as e:
            return False, f"Invalid JSON: {str(e)}", None
        
        # Check depth recursively
        def get_depth(obj, current_depth=0):
            if current_depth > max_depth:
                return current_depth
            if isinstance(obj, dict):
                return max(get_depth(v, current_depth + 1) for v in obj.values()) if obj else current_depth
            elif isinstance(obj, list):
                return max(get_depth(item, current_depth + 1) for item in obj) if obj else current_depth
            else:
                return current_depth
        
        depth = get_depth(parsed)
        if depth > max_depth:
            return False, f"JSON depth ({depth}) exceeds maximum allowed ({max_depth})", parsed
        
        return True, None, parsed
    
    # ============================================
    # 3. Input Length Validation
    # ============================================
    
    def validate_input_length(self, text: str) -> Tuple[bool, Optional[str]]:
        """Check if input is within acceptable length"""
        if not isinstance(text, str):
            return False, "Input is not a string"
        
        length = len(text)
        if length > self.config.max_input_length:
            return False, f"Input too long: {length} chars (max: {self.config.max_input_length})"
        
        return True, None
    
    # ============================================
    # 4. ASCII/Unicode Validation
    # ============================================
    
    def validate_ascii_content(self, text: str, strict: bool = False) -> Tuple[bool, Optional[str]]:
        """
        Check for non-ASCII characters that might indicate injection attacks
        strict=True: Only ASCII allowed
        strict=False: Unicode allowed but validated
        """
        if not isinstance(text, str):
            return False, "Input is not a string"
        
        if strict:
            try:
                text.encode('ascii')
                return True, None
            except UnicodeEncodeError as e:
                return False, f"Non-ASCII characters detected at position {e.start}"
        else:
            # Check for suspicious Unicode (like zero-width characters, right-to-left override, etc.)
            suspicious_chars = [
                '\u200B',  # Zero-width space
                '\u200C',  # Zero-width non-joiner
                '\u200D',  # Zero-width joiner
                '\u202A',  # Left-to-right embedding
                '\u202B',  # Right-to-left embedding
                '\u202C',  # Pop directional formatting
                '\u202D',  # Left-to-right override
                '\u202E',  # Right-to-left override
                '\uFEFF',  # Zero-width no-break space
            ]
            
            for char in suspicious_chars:
                if char in text:
                    return False, f"Suspicious Unicode character detected: U+{ord(char):04X}"
            
            return True, None
    
    # ============================================
    # 5. Rate Limiting / DDOS Prevention
    # ============================================
    
    def check_url_rate_limit(self, url: str) -> Tuple[bool, Optional[str]]:
        """
        Prevent DDOS by limiting calls to same domain
        Returns: (is_allowed, error_message)
        """
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
        except:
            return False, "Cannot parse domain from URL"
        
        current_time = time.time()
        window_start = current_time - self.config.url_call_window_seconds
        
        # Clean old entries
        self.url_call_tracker[domain] = [
            t for t in self.url_call_tracker[domain] 
            if t > window_start
        ]
        
        # Check limit
        call_count = len(self.url_call_tracker[domain])
        if call_count >= self.config.max_url_calls_per_domain:
            return False, (
                f"Rate limit exceeded for {domain}: "
                f"{call_count} calls in {self.config.url_call_window_seconds}s "
                f"(max: {self.config.max_url_calls_per_domain})"
            )
        
        # Record this call
        self.url_call_tracker[domain].append(current_time)
        return True, None
    
    # ============================================
    # 6. Timeout Configuration
    # ============================================
    
    def get_timeout_config(self) -> int:
        """Return configured timeout for network requests"""
        return self.config.request_timeout_seconds
    
    async def execute_with_timeout(self, coro, timeout: Optional[int] = None):
        """
        Execute coroutine with timeout
        Raises asyncio.TimeoutError if timeout exceeded
        """
        timeout = timeout or self.config.request_timeout_seconds
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            raise HeuristicViolation(
                "TIMEOUT",
                f"Operation exceeded {timeout}s timeout",
                "error"
            )
    
    # ============================================
    # 7. File Input Validation
    # ============================================
    
    def validate_file_inputs(self, file_paths: List[str]) -> Tuple[bool, Optional[str]]:
        """
        Validate file paths and count
        Returns: (is_valid, error_message)
        """
        if not isinstance(file_paths, list):
            file_paths = [file_paths]
        
        # Check count
        if len(file_paths) > self.config.max_files_per_call:
            return False, (
                f"Too many files: {len(file_paths)} "
                f"(max: {self.config.max_files_per_call})"
            )
        
        # Check for dangerous paths
        for path in file_paths:
            for blocked in self.config.blocked_file_operations:
                if blocked.lower() in path.lower():
                    return False, f"Access to {blocked} is blocked for security"
        
        return True, None
    
    # ============================================
    # 8. Dangerous Command Detection
    # ============================================
    
    def validate_command_safety(self, command: str) -> Tuple[bool, Optional[str]]:
        """
        Check for dangerous system commands
        Returns: (is_safe, error_message)
        """
        if not isinstance(command, str):
            return False, "Command is not a string"
        
        command_lower = command.lower()
        
        # Only check non-comment, non-string lines for actual command execution
        # Skip lines that are comments or just variable assignments
        lines = command.split('\n')
        code_lines = []
        for line in lines:
            stripped = line.strip()
            # Skip comments
            if stripped.startswith('#'):
                continue
            # Skip lines that are just variable assignments or f-strings
            # Only check lines that look like actual subprocess/os.system calls
            if any(keyword in stripped for keyword in ['subprocess.', 'os.system(', 'os.popen(', 'exec(', 'eval(']):
                code_lines.append(stripped)
        
        # Only check actual command execution lines
        command_code = '\n'.join(code_lines)
        
        if not command_code:
            # No actual command execution detected
            return True, None
        
        # Check against blocked commands in actual execution lines
        for blocked_cmd in self.config.blocked_commands:
            if blocked_cmd.lower() in command_code.lower():
                return False, f"Dangerous command detected: '{blocked_cmd}'"
        
        # Check for suspicious patterns
        dangerous_patterns = [
            r'rm\s+-[rf]{1,2}\s+/',  # rm -rf /
            r'>\s*/dev/sd[a-z]',  # > /dev/sda
            r'dd\s+if=.*of=/dev/',  # dd to device
            r'mkfs\.',  # filesystem formatting
            r':()\{.*\|.*&\};:',  # fork bomb
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, command_code.lower()):
                return False, f"Dangerous command pattern detected"
        
        return True, None
    
    # ============================================
    # 9. Tool Registry Validation
    # ============================================
    
    def validate_tool_exists(self, tool_name: str, available_tools: List[str]) -> Tuple[bool, Optional[str]]:
        """
        Verify tool exists in registry
        Returns: (exists, error_message)
        """
        if tool_name not in available_tools:
            return False, (
                f"Tool '{tool_name}' not found in registry. "
                f"Available tools: {', '.join(available_tools[:5])}..."
            )
        return True, None
    
    # ============================================
    # 10. Plan/Code Validation
    # ============================================
    
    def validate_generated_plan(self, plan_code: str) -> Tuple[bool, Optional[str]]:
        """
        Validate generated solve() code for safety
        Returns: (is_safe, error_message)
        """
        # Check length
        valid, msg = self.validate_input_length(plan_code)
        if not valid:
            return False, f"Plan too long: {msg}"
        
        # Check for dangerous imports/operations
        dangerous_patterns = [
            (r'\bsubprocess\b', 'subprocess'),
            (r'\bos\.system\b', 'os.system'),
            (r'\beval\s*\(', 'eval'),
            (r'\bexec\s*\(', 'exec'),
            (r'\b__import__\s*\(', '__import__'),
            (r'\bopen\s*\(', 'open'),  # Only match open() as function call
            (r'\bfile\s*\(', 'file'),
            (r'\binput\s*\(', 'input'),
            (r'\braw_input\s*\(', 'raw_input'),
            (r'\bexecfile\s*\(', 'execfile'),
        ]
        
        for pattern, name in dangerous_patterns:
            # Check each line, skip comments
            lines = plan_code.split('\n')
            for line in lines:
                stripped = line.strip()
                if stripped.startswith('#'):
                    continue
                # Use regex to match actual function calls, not just the word
                if re.search(pattern, line):
                    return False, f"Dangerous operation '{name}' detected in plan"
        
        # Check for dangerous commands within the code
        valid, msg = self.validate_command_safety(plan_code)
        if not valid:
            return False, f"Dangerous command in plan: {msg}"
        
        return True, None
    
    # ============================================
    # Additional Heuristics
    # ============================================
    
    def validate_recursion_depth(self, current_depth: int, max_depth: int = 10) -> Tuple[bool, Optional[str]]:
        """Prevent infinite recursion"""
        if current_depth > max_depth:
            return False, f"Recursion depth {current_depth} exceeds maximum {max_depth}"
        return True, None
    
    def validate_memory_usage(self, data_size_bytes: int, max_size_mb: int = 100) -> Tuple[bool, Optional[str]]:
        """Check if data size is within limits"""
        max_bytes = max_size_mb * 1024 * 1024
        if data_size_bytes > max_bytes:
            return False, f"Data size {data_size_bytes / (1024*1024):.2f}MB exceeds limit {max_size_mb}MB"
        return True, None
    
    def validate_api_key_exposure(self, text: str) -> Tuple[bool, Optional[str]]:
        """Check for accidentally exposed API keys or secrets"""
        # Common API key patterns
        patterns = [
            r'api[_-]?key["\']?\s*[:=]\s*["\']([a-zA-Z0-9_\-]{20,})',
            r'secret[_-]?key["\']?\s*[:=]\s*["\']([a-zA-Z0-9_\-]{20,})',
            r'password["\']?\s*[:=]\s*["\']([^"\']{8,})',
            r'(sk|pk)_[a-z]{4,}_[a-zA-Z0-9]{20,}',  # Stripe-like keys
            r'AIza[0-9A-Za-z\\-_]{35}',  # Google API keys
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return False, "Potential API key or secret detected in input. Please use environment variables."
        
        return True, None
    
    def validate_sql_injection(self, query: str) -> Tuple[bool, Optional[str]]:
        """Basic SQL injection detection"""
        suspicious_patterns = [
            r"'\s*OR\s+'1'\s*=\s*'1",
            r";\s*DROP\s+TABLE",
            r"UNION\s+SELECT",
            r"--\s*$",
            r"'\s*;",
        ]
        
        for pattern in suspicious_patterns:
            if re.search(pattern, query, re.IGNORECASE):
                return False, "Potential SQL injection pattern detected"
        
        return True, None
    
    # ============================================
    # Comprehensive Validation Pipeline
    # ============================================
    
    async def validate_tool_call(
        self, 
        tool_name: str,
        tool_args: Dict[str, Any],
        available_tools: List[str]
    ) -> Tuple[bool, List[str]]:
        """
        Run all relevant validations for a tool call
        Returns: (is_valid, list_of_errors)
        """
        errors = []
        
        # 1. Tool exists
        valid, msg = self.validate_tool_exists(tool_name, available_tools)
        if not valid:
            errors.append(msg)
        
        # 2. Check arguments
        try:
            args_str = json.dumps(tool_args)
            
            # Validate JSON structure
            valid, msg, _ = self.validate_json_input(args_str)
            if not valid:
                errors.append(f"Tool args validation: {msg}")
            
            # Check for API key exposure
            valid, msg = self.validate_api_key_exposure(args_str)
            if not valid:
                errors.append(msg)
            
        except Exception as e:
            errors.append(f"Error validating tool args: {str(e)}")
        
        # 3. Tool-specific validations
        if 'url' in tool_args or 'input' in tool_args:
            input_dict = tool_args.get('input', {})
            if isinstance(input_dict, dict) and 'url' in input_dict:
                url = input_dict['url']
                valid, msg = self.validate_url(url)
                if not valid:
                    errors.append(f"URL validation: {msg}")
                else:
                    # Check rate limit
                    valid, msg = self.check_url_rate_limit(url)
                    if not valid:
                        errors.append(f"Rate limit: {msg}")
        
        # 4. File path validation
        if 'file_path' in tool_args or 'path' in tool_args:
            input_dict = tool_args.get('input', {})
            if isinstance(input_dict, dict):
                file_path = input_dict.get('file_path') or input_dict.get('path')
                if file_path:
                    valid, msg = self.validate_file_inputs([file_path])
                    if not valid:
                        errors.append(f"File validation: {msg}")
        
        # 5. Command validation
        if 'command' in tool_args or 'code' in tool_args:
            input_dict = tool_args.get('input', {})
            if isinstance(input_dict, dict):
                cmd = input_dict.get('command') or input_dict.get('code', '')
                if cmd:
                    valid, msg = self.validate_command_safety(cmd)
                    if not valid:
                        errors.append(f"Command safety: {msg}")
        
        # 6. Query validation (SQL injection)
        if 'query' in tool_args:
            input_dict = tool_args.get('input', {})
            if isinstance(input_dict, dict) and 'query' in input_dict:
                query = input_dict['query']
                if isinstance(query, str):
                    valid, msg = self.validate_sql_injection(query)
                    if not valid:
                        errors.append(f"SQL injection check: {msg}")
        
        return len(errors) == 0, errors
    
    def get_validation_report(self) -> Dict[str, Any]:
        """Get current state of validator"""
        return {
            "session_duration_seconds": time.time() - self.session_start_time,
            "url_calls_by_domain": {
                domain: len(calls) 
                for domain, calls in self.url_call_tracker.items()
            },
            "total_tool_calls": sum(self.tool_call_tracker.values()),
            "config": self.config.dict()
        }


# ============================================
# Global Validator Instance
# ============================================

# Create a global validator for the session
_global_validator: Optional[HeuristicValidator] = None

def get_validator() -> HeuristicValidator:
    """Get or create global validator instance"""
    global _global_validator
    if _global_validator is None:
        _global_validator = HeuristicValidator()
    return _global_validator

def reset_validator():
    """Reset global validator (useful for new sessions)"""
    global _global_validator
    _global_validator = HeuristicValidator()

