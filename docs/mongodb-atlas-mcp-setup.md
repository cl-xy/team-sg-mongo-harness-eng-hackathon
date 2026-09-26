# MongoDB Atlas MCP Setup

This guide connects the team to the hackathon sandbox's project-level Atlas MCP configuration. It uses a dedicated MCP client ID and secret, not the Atlas public/private API keys in `.env`.

## Atlas CLI login

Install and authenticate the Atlas CLI:

```sh
brew install mongodb-atlas-cli
atlas auth login -P mcp
```

Choose `UserAccount`, complete browser verification, select the hackathon organisation (`69ef9daf03d2ce35c2657862`), and choose JSON output. Set the sandbox project as the profile default and verify access:

```sh
atlas config set project_id 6ab7f90803cb818a58e05a03 -P mcp
atlas projects list -P mcp
atlas clusters list -P mcp
```

## Get MCP credentials

The project MCP configuration is `team-sg-311-harness` (`8149250a-cbe2-4a76-a3f1-0e68d6edea14`). It currently grants `GROUP_OWNER` access and has an IP access list. **Ask the project owner to add your current public egress IP and share the client ID and secret with you through an approved password manager.** The secret is shown only when created; do not put it in Git, chat, or `.env` committed to the repository.

The project owner can inspect the configuration with:

```sh
atlas api remoteMcpConfigurations getGroupMcpConfig \
  --groupId 6ab7f90803cb818a58e05a03 \
  --mcpConfigId 8149250a-cbe2-4a76-a3f1-0e68d6edea14 \
  -P mcp
```

If a teammate's IP is not allowed, the owner updates the configuration's `ipAccessList` using `atlas api remoteMcpConfigurations updateGroupMcpConfig`. Preserve the existing entries when adding an IP. Each teammate should use their own Atlas CLI login; do not share personal Atlas API keys.

## Configure Codex

Add this server block to `~/.codex/config.toml` (or merge it into the existing file). Replace the placeholders with credentials received securely:

```toml
[mcp_servers.mongodb-atlas-mcp-remote]
command = "npx"
args = ["-y", "mongodb-atlas-mcp-remote@latest"]

[mcp_servers.mongodb-atlas-mcp-remote.env]
MDB_MCP_API_CLIENT_ID = "<client-id>"
MDB_MCP_API_CLIENT_SECRET = "<client-secret>"
```

Restart Codex, then confirm the Atlas tools are available. The credentials provide the configured project-level `GROUP_OWNER` access, so treat them as privileged credentials. Rotate/revoke them if exposed; the project owner can manage MCP secrets with `atlas api remoteMcpConfigurations`.

The local `mcp-client-config.toml` generated during setup is Git-ignored and must remain local. Atlas CLI authentication and this MCP client configuration are separate; completing `atlas auth login` alone does not register MCP tools in Codex.
