# rust: let the compiler check every change

- After every change, `cargo check`. Read the first error whole, `help:` lines included - the compiler usually says what the fix is. Fix that one, check again.
- Before handing over: `cargo fmt`, `cargo clippy` (with `-- -D warnings` if the project is clean of them), and `cargo test`. Show it working with `cargo run`, with arguments if the program takes them.
- Borrow before you clone. A `.clone()` added only to quiet the borrow checker is a sign to restructure; if it is really fine, say why.
- Errors are `Result` and `?`. No `unwrap()` or `expect()` outside tests and examples, unless failing is truly impossible - and then `expect` says why. A binary may use `anyhow` if it already does; a library has its own error type.
- No `unsafe` unless it was asked for.
- No new crate without asking. When one is agreed, `cargo add` it.
- Prefer `match`, `if let` and iterators to index loops and flag variables, as far as the code around them reads that way.
