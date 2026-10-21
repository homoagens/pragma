# show_image

Show the person an image file, PNG or JPEG: it is drawn in their terminal. Nothing needs installing.

---

## Parameters

- `path` (str): Absolute path of the image file.

## Returns

The image's size and how wide it was drawn, or `ERROR: not shown` and why. The picture is coarse: shapes and colours show, small text does not.

It shows the image to the person, not to you. To look at an image yourself, use `vision_interpret`.

## Where it is offered

Only in a conversation, where a person is watching the terminal: `agent/chat.py` offers its own version, and the picture is drawn under the step that called it. A batch run and a [served project](../../../docs/how-to/serve-a-project.md) do not offer it.

Without Pillow, PNG and JPEG are read by Pragma itself: a progressive JPEG from its first pass only, and other formats not at all. With Pillow installed, any format it reads.

## Examples

```json
{ "action": "show_image", "args": { "path": "/home/me/project/chart.png" } }
```

## Do not

- Install an image viewer, or write the image out as base64, to show an image: this does it.
- Call it to look at an image yourself: it shows you nothing.
