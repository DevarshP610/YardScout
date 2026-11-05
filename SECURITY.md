# Security policy

## Reporting a vulnerability

Do not open a public issue for a security vulnerability. Use GitHub's private security advisory flow for this repository, or contact the maintainers privately through the repository profile.

Include:

- The affected URL, file, or component.
- Reproduction steps and expected versus actual behavior.
- Potential impact.
- A suggested fix, if you have one.

Please avoid sharing credentials, personal data, production backups, or exploit payloads that could harm other users.

## Supported versions

Security fixes target the latest commit on `main`. Deployments should use a current dependency install and a strong `SECRET_KEY`; credentials must be stored in hosting-provider secrets, never in the repository.
