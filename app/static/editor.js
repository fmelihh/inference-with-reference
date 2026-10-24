// Versions are pinned in the import map in editor.html.
import { basicSetup } from "codemirror";
import { MergeView } from "@codemirror/merge";
import { EditorState, RangeSetBuilder, StateField } from "@codemirror/state";
import { Decoration, EditorView, ViewPlugin, WidgetType } from "@codemirror/view";
import { HighlightStyle, syntaxHighlighting, syntaxTree } from "@codemirror/language";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { tags } from "@lezer/highlight";

const $ = (id) => document.getElementById(id);
const docId = location.pathname.split("/").pop();

let original = "";
let proposed = null;
let editor = null;
let merge = null;

const prose = "system-ui, -apple-system, sans-serif";
const markdownStyle = HighlightStyle.define([
  { tag: tags.heading1, fontSize: "1.7em", fontWeight: "700", fontFamily: prose },
  { tag: tags.heading2, fontSize: "1.4em", fontWeight: "700", fontFamily: prose },
  { tag: tags.heading3, fontSize: "1.2em", fontWeight: "700", fontFamily: prose },
  { tag: [tags.heading4, tags.heading5, tags.heading6], fontWeight: "700", fontFamily: prose },
  { tag: tags.strong, fontWeight: "700" },
  { tag: tags.emphasis, fontStyle: "italic" },
  { tag: tags.strikethrough, textDecoration: "line-through" },
  { tag: tags.link, color: "var(--accent)", textDecoration: "underline" },
  { tag: tags.processingInstruction, color: "var(--muted)" },
]);

// Hide "## " heading marks except on lines the selection touches, so the
// document text (and every offset sent to the API) stays unchanged.
const hiddenMark = Decoration.replace({});
function headingMarks(view) {
  const builder = new RangeSetBuilder();
  const { doc, selection } = view.state;
  const active = new Set();
  for (const r of selection.ranges) {
    for (let n = doc.lineAt(r.from).number; n <= doc.lineAt(r.to).number; n++) active.add(n);
  }
  for (const { from, to } of view.visibleRanges) {
    syntaxTree(view.state).iterate({
      from, to,
      enter(node) {
        if (node.name !== "HeaderMark") return;
        const line = doc.lineAt(node.from);
        if (active.has(line.number) || node.from !== line.from) return;
        const end = doc.sliceString(node.to, node.to + 1) === " " ? node.to + 1 : node.to;
        builder.add(node.from, end, hiddenMark);
      },
    });
  }
  return builder.finish();
}
const hideHeadingMarks = ViewPlugin.fromClass(
  class {
    constructor(view) { this.decorations = headingMarks(view); }
    update(u) {
      if (u.docChanged || u.selectionSet || u.viewportChanged || syntaxTree(u.startState) !== syntaxTree(u.state)) {
        this.decorations = headingMarks(u.view);
      }
    }
  },
  { decorations: (v) => v.decorations },
);
const markdownView = [markdown({ base: markdownLanguage }), syntaxHighlighting(markdownStyle)];

// Show GFM tables as real tables unless the selection touches them; clicking a
// table moves the cursor into it and reveals the Markdown source for editing.
const escapeHtml = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const inline = (s) => escapeHtml(s)
  .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
  .replace(/\*(.+?)\*/g, "<em>$1</em>")
  .replace(/`(.+?)`/g, "<code>$1</code>");
const cells = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());

class TableWidget extends WidgetType {
  constructor(source, from) { super(); this.source = source; this.from = from; }
  eq(other) { return other.source === this.source && other.from === this.from; }
  toDOM(view) {
    const [head, delim, ...rows] = this.source.split("\n").filter((l) => l.trim());
    const align = cells(delim).map((c) => (c.endsWith(":") ? (c.startsWith(":") ? "center" : "right") : "left"));
    const row = (line, tag) => `<tr>${cells(line).map((c, i) => `<${tag} style="text-align:${align[i] || "left"}">${inline(c)}</${tag}>`).join("")}</tr>`;
    const wrap = document.createElement("div");
    wrap.className = "cm-md-table";
    wrap.innerHTML = `<table><thead>${row(head, "th")}</thead><tbody>${rows.map((r) => row(r, "td")).join("")}</tbody></table>`;
    wrap.addEventListener("mousedown", (e) => {
      e.preventDefault();
      view.dispatch({ selection: { anchor: this.from } });
      view.focus();
    });
    return wrap;
  }
  ignoreEvent() { return false; }
}

function tableDecorations(state) {
  const builder = new RangeSetBuilder();
  const sel = state.selection.ranges;
  syntaxTree(state).iterate({
    enter(node) {
      if (node.name !== "Table") return;
      const from = state.doc.lineAt(node.from).from;
      const to = state.doc.lineAt(node.to).to;
      if (sel.some((r) => r.from <= to && r.to >= from)) return false;
      builder.add(from, to, Decoration.replace({
        widget: new TableWidget(state.doc.sliceString(from, to), from),
        block: true,
      }));
      return false;
    },
  });
  return builder.finish();
}
const renderTables = StateField.define({
  create: tableDecorations,
  update(deco, tr) {
    const changed = tr.docChanged || tr.selection || syntaxTree(tr.startState) !== syntaxTree(tr.state);
    return changed ? tableDecorations(tr.state) : deco;
  },
  provide: (f) => EditorView.decorations.from(f),
});

// CodeMirror positions are UTF-16 units; Python slices by code point.
const codePoints = (doc, pos) => [...doc.sliceString(0, pos)].length;

function selectionRange() {
  const { from, to } = editor.state.selection.main;
  return from === to ? null : { from, to };
}

function updateChip() {
  $("chip").textContent = selectionRange() ? "Selection" : "Whole document";
}

async function load() {
  const { meta, text } = await (await fetch(`/api/documents/${docId}`)).json();
  original = text;
  $("name").textContent = meta.name;
  document.title = `${meta.name} · Editor`;
  editor?.destroy();
  editor = new EditorView({
    parent: $("editor"),
    state: EditorState.create({
      doc: text,
      extensions: [
        basicSetup,
        EditorView.lineWrapping,
        markdownView,
        hideHeadingMarks,
        renderTables,
        EditorView.updateListener.of((u) => { if (u.selectionSet) updateChip(); }),
      ],
    }),
  });
  updateChip();
  fetch(`/api/documents/${docId}/prime`, { method: "POST" });
}

function showDiff(text) {
  proposed = text;
  merge?.destroy();
  merge = new MergeView({
    parent: $("diff"),
    a: { doc: original, extensions: [basicSetup, EditorView.editable.of(false), EditorView.lineWrapping, markdownView] },
    b: { doc: text, extensions: [basicSetup, EditorView.editable.of(false), EditorView.lineWrapping, markdownView] },
  });
  $("edit-view").hidden = true;
  $("diff-view").hidden = false;
}

function closeDiff() {
  merge?.destroy();
  merge = null;
  proposed = null;
  $("diff-view").hidden = true;
  $("edit-view").hidden = false;
}

function clearSelection() {
  if (selectionRange()) editor.dispatch({ selection: { anchor: editor.state.selection.main.head } });
}

// Clicking outside the text deselects; the instruction box and Run keep the selection.
document.addEventListener("mousedown", (e) => {
  if (editor && !e.target.closest("#editor, #run-form")) clearSelection();
});

$("run-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("error").textContent = "";
  const range = selectionRange();
  const doc = editor.state.doc;
  const selection = range && { from: codePoints(doc, range.from), to: codePoints(doc, range.to) };
  clearSelection();
  $("run").disabled = true;
  $("strip").textContent = "Running…";
  try {
    const resp = await fetch(`/api/documents/${docId}/edit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruction: $("instruction").value, selection }),
    });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(body.detail);
    }
    const { proposed_text, run } = await resp.json();
    $("strip").textContent =
      `${run.mode} · ${run.seconds.toFixed(2)} s · ${run.output_tokens} tokens · ${run.tokens_per_second.toFixed(1)} tok/s`;
    showDiff(proposed_text);
  } catch (err) {
    $("strip").textContent = "";
    $("error").textContent = err.message;
  } finally {
    $("run").disabled = false;
  }
});

$("accept").addEventListener("click", async () => {
  await fetch(`/api/documents/${docId}/versions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: proposed }),
  });
  closeDiff();
  await load();
});

$("reject").addEventListener("click", closeDiff);

fetch("/api/config").then((r) => r.json()).then((c) => { $("mode").textContent = c.spec_mode; });
load();
