# `edge/api/`

**Filled in its own run.** A stable internal API the consoles call, so a console never touches the
store directly. The process/logic lives here behind an interface — change a *process* (a flow/policy)
→ change here, not the UIs. One of the three swap-seams (hardware / UI / process).
