# html: valid, accessible, works at phone width, and checked

- Structure: `<!doctype html>`, `<html lang="...">`, `<meta charset="utf-8">`, the viewport meta, one `<h1>`, and `header`, `main`, `nav`, `footer` where they belong.
- A small page can be one file. A larger one has its HTML, CSS and JavaScript in their own files, linked by relative paths - never an absolute path on this disk.
- Accessible: `alt` on every image, a `label` for every input, buttons for actions and links for places, readable contrast, a visible focus.
- Layout with flexbox or grid. It must work at phone width: nothing scrolls sideways at 375 pixels.
- JavaScript: `const` and `let`, `addEventListener` rather than `onclick=` in the markup, and a check that an element exists before using it. Put data on the page with `textContent`, not `innerHTML`.
- No framework, CDN or external font unless asked: a page that needs none should not carry one.
- Check it: the tags balance; serve the folder (`python -m http.server`) and fetch the page with `curl`; open it in a browser if there is one. Say what you could not check - how it looks, above all.
