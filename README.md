# nops

[![Tests](https://github.com/sapp00/nops/actions/workflows/test.yml/badge.svg)](https://github.com/sapp00/nops/actions/workflows/test.yml)

**nops** (nice ops / nix ops) is a simple CLI tool for managing SOPS encryption keys. It helps you create, store, and manage project-specific age keys encrypted with your master key.

## Features

- **Simple key management**: Create and store multiple age keys per project
- **Encrypted storage**: All project keys encrypted with your master key (safe to commit to git)
- **Automatic project detection**: Finds `.sops.yaml` by traversing up directory tree
- **Master key access**: Your master key can always decrypt everything
- **Granular access**: Export specific keys for servers/environments
- **Clean CLI**: Intuitive commands for daily workflows

## How It Works

1. **Master key** (`~/.sops/key.txt`): Your personal key, used for daily encrypt/decrypt operations
2. **Project keys** (`.sops/keys.txt.age`): Additional keys for specific servers/environments, encrypted with master key, committed to git
3. **`.sops.yaml`**: SOPS config containing public keys (including your master key's public key)

**Daily workflow:**
- Use your master key to edit/encrypt secrets (it's in `.sops.yaml`)
- Project keys stored encrypted in git
- Decrypt project keys only when managing them or deploying to servers

## Installation

### With Nix Flakes

Add to your `flake.nix`:

```nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    nops.url = "github:sapp00/nops";
  };

  outputs = { self, nixpkgs, nops }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
    in {
      devShells.${system}.default = pkgs.mkShell {
        buildInputs = [
          nops.packages.${system}.default
          pkgs.sops
          pkgs.age
        ];
      };
    };
}
```

### Prerequisites

- `age` - Age encryption tool
- `sops` - Mozilla SOPS for secrets management
- Master key at `~/.sops/key.txt`

Generate master key if you don't have one:
```bash
mkdir -p ~/.sops
age-keygen -o ~/.sops/key.txt
```

**Important**: Back up your master key securely!

## Quick Start

```bash
# 1. Initialize a new project
cd my-project
nops init

# 2. Create additional keys for servers/environments
nops create server1
nops create server2
nops create prod

# 3. Edit .sops.yaml to configure path-based rules
vim .sops.yaml

# 4. Encrypt/edit secrets
nops secrets/server1.yaml
nops encrypt secrets/config.yaml

# 5. Export keys for deployment
nops export server1 > server1.key
```

## Commands

### `nops init`

Initialize a new nops project. Creates `.sops.yaml` with your master key and empty `.sops/keys.txt.age`.

```bash
nops init
```

### `nops create <name>`

Create a new project key. Generates a fresh age key pair, encrypts it, and adds the public key to `.sops.yaml`.

```bash
nops create server1
nops create prod
```

After creating keys, manually edit `.sops.yaml` to add them to `creation_rules`.

### `nops <file>`

Edit an encrypted file with SOPS using your master key.

```bash
nops secrets/prod.yaml
```

Works from any subdirectory - automatically finds project root.

### `nops encrypt <file>`

Encrypt a plaintext file in-place using SOPS.

```bash
nops encrypt secrets/new-config.yaml
```

### `nops export <name>`

Export a specific key (for deploying to servers).

```bash
nops export server1 > /tmp/server1.key
scp /tmp/server1.key server1:/etc/sops/key.txt
```

### `nops updatekeys [path]`

Update encryption keys for all SOPS-encrypted files after modifying `.sops.yaml`. Shows diffs for each file and asks for confirmation before applying changes.

```bash
# Update all encrypted files in secrets directory (interactive)
nops updatekeys secrets/

# Update specific file (interactive)
nops updatekeys secrets/prod.yaml

# Update all encrypted files in current directory (default)
nops updatekeys

# Auto-confirm without showing diffs (for CI/CD)
nops updatekeys -y secrets/
```

## Configuration

### `.sops.yaml`

After running `nops init` and creating keys, edit `.sops.yaml` to configure path-based access rules:

```yaml
keys:
  - master: &master age1abcd...
  - server1: &server1 age1efgh...
  - server2: &server2 age1ijkl...

creation_rules:
  # Server 1 secrets - accessible by master + server1
  - path_regex: secrets/server1/.*\.(yaml|json|env)$
    key_groups:
      - age:
          - *master
          - *server1

  # Server 2 secrets - accessible by master + server2
  - path_regex: secrets/server2/.*\.(yaml|json|env)$
    key_groups:
      - age:
          - *master
          - *server2

  # Common secrets - accessible by all
  - path_regex: secrets/common/.*\.(yaml|json|env)$
    key_groups:
      - age:
          - *master
          - *server1
          - *server2

  # Default: only master key
  - path_regex: .*
    key_groups:
      - age:
          - *master
```

### `.sops/keys.txt.age`

Encrypted file containing all project keys. Safe to commit to git.

```
# Encrypted with master key
# Can be decrypted with: age -d -i ~/.sops/key.txt .sops/keys.txt.age
```

## Project Structure

```
my-project/
├── flake.nix
├── .sops.yaml              # SOPS config (committed)
├── .sops/
│   └── keys.txt.age        # Encrypted project keys (committed)
└── secrets/
    ├── server1/
    │   └── config.yaml     # Encrypted for: master + server1
    ├── server2/
    │   └── config.yaml     # Encrypted for: master + server2
    └── common/
        └── shared.yaml     # Encrypted for: master + server1 + server2
```

**Committed to git:**
- `.sops.yaml` - SOPS configuration
- `.sops/keys.txt.age` - Encrypted project keys
- `secrets/**/*.yaml` - Encrypted secrets

**Never committed:**
- `~/.sops/key.txt` - Your personal master key

## Security Model

### Master Key
- Stored in `~/.sops/key.txt` (your home directory)
- Public key included in every `.sops.yaml`
- Can decrypt all secrets in any project
- Back it up securely!

### Project Keys
- Generated fresh for each key name
- Encrypted with master key's public key
- Stored in `.sops/keys.txt.age` (safe to commit)
- Only decrypted when managing keys or deploying

### Threat Model

**External attacker (no access to keys):**
- ❌ Cannot decrypt `.sops/keys.txt.age`
- ❌ Cannot decrypt secrets
- ✅ Secure

**Master key compromise:**
- ✅ Can decrypt all project keys
- ✅ Can decrypt all secrets
- Mitigation: Protect master key, rotate if compromised

**Project key compromise (e.g., server1):**
- ✅ Can decrypt `secrets/server1/*`
- ❌ Cannot decrypt other servers' secrets
- Mitigation: Rotate specific key, re-encrypt affected secrets

## Workflows

### Daily Development

```bash
# Edit encrypted secrets
nops secrets/database.yaml

# Add new secret
echo "password: secret123" > secrets/new.yaml
nops encrypt secrets/new.yaml

# Commit changes
git add secrets/ .sops/
git commit -m "Update secrets"
```

### Adding a New Server

```bash
# Create key for new server
nops create server3

# Edit .sops.yaml to add path rule
vim .sops.yaml

# Create secrets for new server
nops secrets/server3/config.yaml

# Export key for deployment
nops export server3 | ssh server3 "cat > /etc/sops/key.txt"
```

### Rotating a Compromised Key

```bash
# 1. Remove old key from .sops.yaml
vim .sops.yaml

# 2. Create new key with same name
# First, manually decrypt and remove from .sops/keys.txt.age
# Then create fresh:
nops create server1-new

# 3. Update .sops.yaml to use new key
vim .sops.yaml

# 4. Re-encrypt affected secrets
sops updatekeys secrets/server1/*.yaml

# 5. Deploy new key
nops export server1-new | ssh server1 "cat > /etc/sops/key.txt"
```

### Team Onboarding

```bash
# New team member generates master key
age-keygen -o ~/.sops/key.txt

# Add their master public key to .sops.yaml
vim .sops.yaml  # Add age1xyz... to relevant rules

# Re-encrypt all secrets to include new key
sops updatekeys secrets/**/*.yaml

# They can now decrypt secrets
nops secrets/database.yaml
```

## Comparison to Other Approaches

### vs. KDF-based key derivation
- **nops**: Fresh random keys, encrypted storage
- **KDF**: Deterministic derivation from master + salt
- **Why nops**: Simpler, standard tools, keys survive repo renames

### vs. Plain SOPS
- **nops**: Manages key creation/storage, encrypted key file
- **SOPS**: Requires manual key management
- **Why nops**: Easier key management, safe to commit encrypted keys

### vs. Shared master key only
- **nops**: Master + per-server keys
- **Shared**: Everyone has same access level
- **Why nops**: Granular access control, limit server access

## Troubleshooting

### "No .sops.yaml found"

Run `nops init` in your project root to initialize.

### "Missing master key"

Generate a master key:
```bash
mkdir -p ~/.sops
age-keygen -o ~/.sops/key.txt
```

### "age command not found"

Install age:
```bash
nix-shell -p age
# or
apt install age  # Debian/Ubuntu
brew install age # macOS
```

### "Failed to decrypt keys file"

Ensure you have the correct master key in `~/.sops/key.txt` that was used to encrypt `.sops/keys.txt.age`.

## Contributing

Issues and pull requests welcome at [github.com/sapp00/nops](https://github.com/sapp00/nops).

## License

MIT
