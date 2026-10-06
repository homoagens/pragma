# Move a project to another machine

*For the terminal. Tried on Linux; [what differs on Windows and in the browser](../explanation/interfaces.md).*

A project is two folders and one line in a list: the folder you work in, the
memory Pragma keeps for it, and the entry that ties them together. Pragma has
no command that moves all three, so this is done by hand. It takes five
minutes.

`~` below is your home folder: `/home/you` on Linux, `/Users/you` on macOS,
`C:\Users\you` on Windows.

## On the old machine

1. **Let the memory finish.** Close the project with **ctrl+D** and type
   `/jobs`. Wait until nothing is being written: a conversation still being
   turned into memory is not in the files yet.
2. **Find the two folders.** Open the project once more and type `/status`.
   The lines `workspace` and `store` are the two paths.

## Copy

3. Copy the **workspace** folder to the new machine, wherever you want it.
4. Copy the **store** folder — `~/.pragma/projects/<name>` — somewhere you can
   reach it from the new machine. Do not put it in place yet.

## On the new machine

5. Install Pragma and [connect a model](connect-a-model.md).
6. **Make the project**, with `/new`: the same name, and the folder you
   copied in step 3. This writes the entry and creates an empty memory at
   `~/.pragma/projects/<name>`. Close the project again with **ctrl+D**.
7. **Put the memory in place.** Replace the contents of that empty folder
   with the contents of the store you copied in step 4: the `episodes` folder
   (with `dormant` inside it, if there is one) and `learnings.json`.
8. **Open the project.** The briefing should count the same episodes and
   beliefs as it did on the old machine.

## One thing does not travel

Every episode records the folder it was written in, and an episode written in
the folder you are working in has a small advantage over the rest when Pragma
decides what to recall.

If the folder has a different path on the new machine — it always does
between Windows and Linux — the episodes you brought are treated as written
somewhere else. They are all still there and still recalled; they have only
lost that edge over episodes made from now on.

To keep it, the old path has to be replaced by the new one in the `workspace`
field of each file in `episodes`. Take a copy of the folder first. (Beliefs
carry the same path as `label`; it is only shown, never used to choose.)

## If something looks wrong

- **The briefing shows 0 episodes.** The files went one level too deep:
  `~/.pragma/projects/<name>/episodes/` must hold the `ep_….json` files
  directly.
- **`/new` refuses the name.** A project with that name already exists on
  this machine: pick another, the name does not have to match.
