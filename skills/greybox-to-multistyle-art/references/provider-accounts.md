# Account systems, fixed API routes and recovery identity

Treat provider documentation, installed code, configured credential names, authenticated account access, operation success and native usefulness as separate evidence. Site language does not select an account, and a successful balance call proves only that account-read operation. No preflight or balance grants generation authority.

Every newly prepared built-in supplier production run records `provider.account_profile` in its frozen registry. Select the user's actual account system and local alias before reading credentials; never retry another region/key after auth failure. Endpoints come only from the checked fixed map:

| Provider | `account_system` | API base |
|---|---|---|
| Meshy | `cn` / `international` | `https://api.meshy.cn` / `https://api.meshy.ai` |
| Tripo v3 | `cn` / `international` | `https://openapi.tripo3d.com/v3` / `https://openapi.tripo3d.ai/v3` |
| Rodin | `public` | `https://api.hyper3d.com` |
| Hi3D / Hitem3D | `public` | `https://api.hitem3d.ai` |

`public` identifies the verified API route; it does not assert that every regional website shares an account or wallet. An additional Rodin/Hi3D CN endpoint or account-migration behavior remains unverified. Do not invent a domain or try a credential against a guessed host. Lux retains its existing explicit `cn` / `international` bridge and secure credential namespace; see [Lux bridge](lux-bridge.md).

Example registry provider field:

```json
{
  "account_profile": {
    "account_system": "cn",
    "account_ref": "studio-main",
    "credential_env": "MESHY_STUDIO_CN_API_KEY",
    "wallet": "meshy-studio-cn"
  }
}
```

Use non-secret stable IDs for `account_ref` and `wallet`. Store only the environment **variable name**, never its value. Names must begin with the provider's uppercase prefix (`MESHY_`, `TRIPO_`, `RODIN_`, `HITEM3D_`) and use uppercase letters, digits and underscores. Hi3D replaces `credential_env` with `credential_envs`: an ordered pair such as `["HITEM3D_STUDIO_CLIENT_ID", "HITEM3D_STUDIO_CLIENT_SECRET"]`. Authentication tokens stay in memory; the adapter never changes process-global environment values. An alias is operator-declared identity, not proof of the provider's account owner.

`account_profiles.profile_digest(provider, profile)` binds provider, profile and fixed API base. Built-in responses report `account_profile`, `account_profile_sha256`, `api_base` and `wallet`. Account verification records (connection, operation and native) must carry the same `account_profile_sha256` to count as ready. Existing evidence for another profile remains historical; refreshing unrelated discovery does not qualify a new account. Changing a profile changes the registry routing digest and invalidates the old selection. Portfolio pricing and any rate-card quote must use that profile's wallet; credits from distinct wallets are never pooled.

The supplier invocation layer first compares the submitted operation, source inputs and existing authorization, then injects the registry profile. Adapters also enforce the profile when called directly through the provider CLI. Submit responses bind recovery to the profile; the runner retains the same profile/digest in `accepted_request`. Status/fetch use this accepted identity and reject a different top-level profile, changed digest or unrelated recovery record. After an ambiguous submission, reconcile that task on that account; do not switch provider/region to duplicate it.

Historical direct adapter requests without a profile retain their legacy defaults for compatibility and recovery. This is not a new-run shortcut: the production prepare entry requires explicit profiles for selected built-in APIs. No account is authenticated by static validation, and offline fixtures do not establish cloud availability or output quality. If a variable's underlying account changes, declare the new alias/profile and refresh account-bound evidence rather than reusing an old alias to preserve readiness.

Primary route references checked 2026-10-21:

- [Meshy CN API](https://docs.meshy.cn/zh/api) and [international API](https://docs.meshy.ai/en/api).
- [Tripo CN v3 introduction](https://developers.tripo3d.com/zh/docs/introduction) and [international v3 introduction](https://developers.tripo3d.ai/en/docs/introduction).
- [Rodin public API](https://docs.hyper3d.ai/en/api-specification/rodin-gen1-1-5).
- [Hi3D API quickstart](https://docs.hi3d.ai/en/api/getting-started/quickstart).
