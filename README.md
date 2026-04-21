# nix-sops-kdf

Deterministic SOPS age key derivation for project-scoped secrets using HKDF (HMAC-based Key Derivation Function).

## Overview

This tool automatically derives project-specific age encryption keys from a single master key using HKDF. It eliminates the need to manage separate age keys for each project while maintaining cryptographic isolation between repositories and environments.

### Key Features

- **Deterministic key derivation**: Same master key + same repo = same derived keys
- **Config-driven key management**: Define multiple keys and path-based access rules in `.sops-kdf.yaml`
- **Path-based encryption**: Different secrets can be encrypted for different recipients (servers, environments)
- **Automatic SOPS configuration**: Generates `.sops.yaml` with proper YAML anchors and creation rules
- **Git safety**: Automatically adds `.sops/` to `.gitignore`
- **Zero key management**: Keys derived on-demand in your dev shell

## How It Works

1. Reads your master key from `~/.sops/key.txt`
2. Reads `.sops-kdf.yaml` to determine which keys and rules you need
3. Derives all referenced keys using HKDF with the git repository name as salt
4. Creates `.sops/keys.txt` with all private keys (for decryption)
5. Creates `.sops.yaml` with YAML anchors and path-based creation rules
6. Exports `SOPS_AGE_KEY_FILE` pointing to the local keys file

## Setup

### 1. Generate a Master Key

Create a master key in your home directory:

```bash
mkdir -p ~/.sops
age-keygen -o ~/.sops/key.txt
```

**Important**: Back up this master key securely. It's the only key you need to remember.

### 2. Add to Your Flake

```nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    sops-kdf.url = "github:sapp00/nix-sops-kdf";
  };

  outputs = { self, nixpkgs, sops-kdf }:
  let
    system = "x86_64-linux";
    pkgs = nixpkgs.legacyPackages.${system};
    kdfTool = sops-kdf.packages.${system}.default;
  in {
    devShells.${system}.default = pkgs.mkShell {
      buildInputs = [ pkgs.sops pkgs.age ];

      shellHook = ''
        export EDITOR=vim
        eval "$(${kdfTool}/bin/sops-kdf-hook)"
      '';
    };
  };
}
```

### 3. Enter Your Dev Shell

```bash
nix develop
```

The hook will automatically:
- Derive your project-specific keys
- Create `.sops/keys.txt` and `.sops.yaml`
- Add `.sops/` to `.gitignore`
- Export `SOPS_AGE_KEY_FILE`

## Usage

### Configuration File

Create a `.sops-kdf.yaml` file in your project root to define keys and access rules:

```yaml
rules:
  # Server 1 specific secrets
  # Decryptable by: project + server_1
  - path_regex: secrets/server-1/[^/]+\.(yaml|json|env|ini)$
    keys:
      - server_1

  # Server 2 specific secrets
  # Decryptable by: project + server_2
  - path_regex: secrets/server-2/[^/]+\.(yaml|json|env|ini)$
    keys:
      - server_2

  # Common secrets accessible by both servers
  # Decryptable by: project + server_1 + server_2
  - path_regex: secrets/common/[^/]+\.(yaml|json|env|ini)$
    keys:
      - server_1
      - server_2

  # Default rule for any other files (only project key)
  - path_regex: .*
    keys: []
```

Keys are automatically derived from the key names used in the rules. The tool will:
1. Scan all rules and collect unique key names (`server_1`, `server_2`)
2. Generate the `project` key (always included)
3. Generate keys for each referenced name: `repo+server_1`, `repo+server_2`

### Simple Projects

If you don't create a `.sops-kdf.yaml` file, the tool generates a single `project` key and a default rule that encrypts all files for that key.

### Encrypting Secrets

Once configured, use SOPS normally:

```bash
# Create/edit a secret file
sops secrets/server-1/config.yaml

# SOPS will automatically encrypt it for: project + server_1
# (based on the path_regex match in .sops.yaml)
```

### Decrypting Secrets

SOPS will automatically use the keys from `.sops/keys.txt` (via `SOPS_AGE_KEY_FILE`):

```bash
# View secrets
sops secrets/server-1/config.yaml

# Decrypt to stdout
sops -d secrets/server-1/config.yaml
```

### Key Distribution

To grant access to specific environments/servers:

1. **Share the entire `.sops/keys.txt`** - Full access to all secrets
2. **Share specific keys** - Extract individual keys from `.sops/keys.txt` for limited access
   - Example: Share only the `server_1` key with Server 1 administrators
   - They can decrypt `secrets/server-1/*` but not `secrets/server-2/*`

## Generated Files

### `.sops/keys.txt`

Contains all derived private age keys (newline-separated with comments):

```
# Auto-generated age keys for SOPS
# DO NOT COMMIT THIS FILE

# project
AGE-SECRET-KEY-1...

# server_1
AGE-SECRET-KEY-1...

# server_2
AGE-SECRET-KEY-1...
```

**Security**: This file has `600` permissions and is auto-ignored by git.

### `.sops.yaml`

SOPS configuration with YAML anchors and path-based creation rules:

```yaml
keys:
  - &project age1...
  - &server_1 age1...
  - &server_2 age1...

creation_rules:
  - path_regex: secrets/server-1/[^/]+\.(yaml|json|env|ini)$
    key_groups:
      - age:
          - *project
          - *server_1
  - path_regex: secrets/server-2/[^/]+\.(yaml|json|env|ini)$
    key_groups:
      - age:
          - *project
          - *server_2
  - path_regex: secrets/common/[^/]+\.(yaml|json|env|ini)$
    key_groups:
      - age:
          - *project
          - *server_1
          - *server_2
```

**Note**: The `project` key is automatically added to all rules. This is auto-generated from `.sops-kdf.yaml`.

### `.gitignore`

Automatically updated to include:

```
.sops/
```

This prevents accidentally committing private keys.

## Security Considerations

### Master Key Protection

Your `~/.sops/key.txt` is the root of trust:
- Back it up securely (password manager, encrypted backup)
- Never commit it to git
- Consider encrypting your home directory

### Derived Key Isolation

Each project gets cryptographically isolated keys:
- Same master key + different repos = completely different keys
- Keys are deterministic: same inputs always produce same outputs
- Uses HKDF-SHA256 for secure key derivation

### Path-Based Access Control

Using path-based rules creates granular access control:
- Server 1 administrators can only decrypt `secrets/server-1/*`
- Server 2 administrators can only decrypt `secrets/server-2/*`
- Both can decrypt `secrets/common/*`
- Each secret path is cryptographically isolated

### Key Distribution

**For development teams** (full access):
1. Share the same master key in their `~/.sops/key.txt`
2. They run `nix develop` to derive the same project keys
3. They can decrypt and edit all secrets

**For production servers** (limited access):
1. Extract the specific key from `.sops/keys.txt`
2. Deploy only that key to the server
3. Server can only decrypt secrets it needs

**To revoke access**:
- Remove the key reference from `.sops-kdf.yaml` rules
- Regenerate keys: re-enter your dev shell
- Re-encrypt affected secrets: `sops updatekeys secrets/**/*.yaml`

## How KDF Works

The tool uses HKDF (HMAC-based Key Derivation Function) with SHA-256:

```python
# Extract phase
PRK = HMAC-SHA256(salt='age-kdf-salt', ikm=master_key)

# Expand phase
OKM = HMAC-SHA256(key=PRK, info=kdf_input + '\x01')

# Encode as bech32
derived_key = bech32_encode('age-secret-key-', OKM)
```

Where `kdf_input` is:
- Project key: `github.com/user/repo`
- Named keys: `github.com/user/repo+server_1`, `github.com/user/repo+server_2`, etc.

Each key is cryptographically isolated - knowing one key reveals nothing about other keys.

## Troubleshooting

### "No .git directory found"

Run the tool inside a git repository with a configured remote origin.

### "No valid key found in ~/.sops/key.txt"

Generate a master key:
```bash
mkdir -p ~/.sops
age-keygen -o ~/.sops/key.txt
```

### "Failed to derive public key"

Ensure `age` is installed and in your PATH:
```bash
nix-shell -p age
```

### Keys not working after changing config

If you modify `.sops-kdf.yaml` (add/remove keys or rules), re-enter your dev shell to regenerate keys, then re-encrypt affected secrets:
```bash
exit  # Exit dev shell
nix develop  # Re-enter to regenerate keys
sops updatekeys secrets/**/*.yaml  # Re-encrypt all secrets
```

## Example Project Structure

```
my-project/
├── flake.nix           # Includes sops-kdf in shellHook
├── .git/               # Git repository
├── .gitignore          # Auto-updated with .sops/
├── .sops-kdf.yaml      # Your key and rule definitions (committed)
├── .sops.yaml          # Auto-generated SOPS config (committed)
├── .sops/
│   └── keys.txt        # Auto-generated private keys (git-ignored)
└── secrets/
    ├── server-1/
    │   └── config.yaml # Encrypted for: project + server_1
    ├── server-2/
    │   └── config.yaml # Encrypted for: project + server_2
    └── common/
        └── shared.yaml # Encrypted for: project + server_1 + server_2
```

**What gets committed**:
- `.sops-kdf.yaml` - Your configuration (rules and key references)
- `.sops.yaml` - Auto-generated SOPS config (can be regenerated)
- `secrets/**/*.yaml` - Encrypted secret files (safe to commit)

**What's git-ignored**:
- `.sops/keys.txt` - Private keys (never commit)

## Contributing

Issues and pull requests welcome at [github.com/sapp00/nix-sops-kdf](https://github.com/sapp00/nix-sops-kdf).

## License

MIT
