# Local SSH Path Proof

Local shell context:

- local user: `huaihsuanhuang`
- local cwd: `/Users/huaihsuanhuang/Documents/ChatGPT/codex official`
- ssh binary: `/usr/bin/ssh`
- ssh version: `OpenSSH_10.2p1, LibreSSL 3.3.6`
- ssh-agent: no loaded identities

Resolved alias:

- alias: `oracle-vm`
- HostName: `213.35.117.57`
- User: `ubuntu`
- Port: `22`
- IdentityFile: `/Users/huaihsuanhuang/Desktop/Keys/Oracle_SSH_keys/ssh-key-2026-03-15.key`
- IdentitiesOnly: `yes`
- ProxyJump: none observed

Alias execution proof:

```text
M26_ORACLE_SSH_OK
vm-dev-01
2026-08-27T09:51:28Z
09:51:29 up 22 days, 5:02, 1 user, load average: 21.74, 23.70, 22.00
```

Conclusion:

The earlier SSH-insufficient classification is superseded for local Codex execution. Codex successfully used the user-local alias path instead of guessing `opc` or `ubuntu` transport manually.

