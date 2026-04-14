import sys
import subprocess
import hashlib
import hmac
import re
from pathlib import Path
import bech32

def log(msg):
    print(msg, file=sys.stderr)

def run():
    log("🔐 Initializing project-scoped secrets...")

    # 1. Check for Git repo
    if not Path(".git").is_dir():
        log("   -> ⚠️  No .git directory found. Run inside a git repository.")
        sys.exit(0)

    # 2. Get remote URL via subprocess
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            capture_output=True, text=True, check=True
        )
        remote_url = result.stdout.strip()
    except subprocess.CalledProcessError:
        log("   -> ⚠️  No remote.origin.url found in git config.")
        sys.exit(0)

    if not remote_url:
        log("   -> ⚠️  No remote.origin.url found.")
        sys.exit(0)

    # 3. Extract Repo ID (the Salt)
    match = re.search(r'[:/]([^/]+/[^/]+?)(?:\.git)?$', remote_url)
    if not match:
        log(f"   -> ⚠️  Could not parse repository ID from {remote_url}")
        sys.exit(0)
        
    repo_id = match.group(1)

    # 4. Load Master Key
    master_key_path = Path.home() / ".sops" / "key.txt"
    if not master_key_path.is_file():
        log(f"   -> ⚠️  Missing master key at {master_key_path}")
        sys.exit(0)

    with open(master_key_path, "r") as f:
        master_key = None
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                master_key = line
                break
                
    if not master_key:
        log(f"   -> ⚠️  No valid key found in {master_key_path}")
        sys.exit(0)

    # 5. Execute HKDF Math
    ikm = master_key.encode()
    info = repo_id.encode()

    prk = hmac.new(b'age-kdf-salt', ikm, hashlib.sha256).digest()
    okm = hmac.new(prk, info + bytes([1]), hashlib.sha256).digest()

    data = bech32.convertbits(okm, 8, 5)
    derived_key = bech32.bech32_encode('age-secret-key-', data).upper()

    # 6. Derive the Public Key automatically
    try:
        process = subprocess.run(
            ["age-keygen", "-y"],
            input=derived_key,
            capture_output=True,
            text=True,
            check=True
        )
        public_key = process.stdout.strip()
    except subprocess.CalledProcessError as e:
        log(f"   -> ⚠️ Failed to derive public key: {e.stderr}")
        sys.exit(1)

    log(f"   -> ✅ SOPS keys dynamically generated for {repo_id}")
    
    # Output BOTH variables to standard out so `eval` catches them
    print(f"export SOPS_AGE_KEY='{derived_key}'")
    print(f"export SOPS_AGE_RECIPIENTS='{public_key}'")

if __name__ == '__main__':
    run()
