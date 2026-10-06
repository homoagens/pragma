# Use a model on another machine

*For the terminal. Tried on Linux; [what differs on Windows and in the browser](../explanation/interfaces.md).*

The model runs on a machine with a GPU; you work on a laptop. Two ways to
join them, depending on what the network between them allows.

## The server is reachable directly

If the other machine accepts connections on the model's port, there is
nothing special to do: [add the endpoint](connect-a-model.md) with that
machine's address instead of `127.0.0.1`.

Most model servers listen only on their own machine unless told otherwise.
With llama.cpp that is `--host 0.0.0.0`. Do this only on a network you trust:
the server has no password unless you give it one.

## Through an SSH tunnel

When all you have is SSH access, a tunnel makes the remote port appear on
your own machine. In a terminal you will leave open:

```
ssh -N -L 8290:localhost:8290 user@gpu-machine
```

The first `8290` is the port on your machine, the second the port the model
listens on over there. Nothing is printed: the command simply stays running.

Then [add the endpoint](connect-a-model.md) as `127.0.0.1:8290`. As far as
Pragma can tell, the model is local.

## When the tunnel dies

A tunnel can stop carrying traffic while its port stays open: the laptop
slept, the network changed, the far end restarted. Pragma then reports

```text
connected, but no answer within 3s
```

which is exactly that case — something accepted the connection and nothing
is behind it. Close the `ssh` command with **ctrl+C** and start it again.

To have SSH notice a dead connection by itself and exit, instead of hanging,
add this to the host's entry in `~/.ssh/config`:

```
ServerAliveInterval 30
ServerAliveCountMax 3
```

## One slot, two callers

A server started with a single slot answers one request at a time. Pragma
makes requests from two places — the conversation, and the memory being
written in the background after you close a project — so on one slot they
wait for each other. With llama.cpp, `-np 2` gives two slots, each with half
the context.
