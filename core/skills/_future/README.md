# Kept for later

Nothing in this folder is offered to the agent: the skill loader skips every
folder whose name starts with an underscore.

These are not retired. They are seeds for the book's Critic, system 7, which
has not been built, and they are kept out of the palette so that the agent does
not call a critic before that critic has been designed.

| skill | what it is |
| --- | --- |
| `critic_validate` | a generic judge: PASS, WARN or FAIL against criteria given in the call |
| `schema_validate` | its structural counterpart: does a JSON string have the required fields and types |

Neither was ever called by the agent in 241 archived runs or in real use. What
the Critic becomes is a design question, not a question of re-enabling these.
