The images above are equations cropped from a scientific paper, in this
order:

{{EQUATION_LIST}}

For each one, give its LaTeX (math-mode content only: no $ signs, no
\[ \], no \begin{equation}). Transcribe exactly what is printed:

- keep every subscript and superscript, and the paper's own symbols and
  names (e.g. k_{\mathrm{cond}}, [\mathrm{peptide}_{n-1}], \Delta G_r^0,
  \delta^{15}\mathrm{N}, ‰ as \text{‰});
- words and chemical names in upright text: \mathrm{...} or \text{...};
- a reaction arrow as \rightarrow, an equilibrium as \rightleftharpoons;
- an equation printed on two lines: keep both parts, joined with \\ inside
  \begin{aligned} ... \end{aligned};
- leave out the equation's number label, e.g. "(1)";
- don't simplify, correct or complete anything. If something is unreadable,
  give your best reading and say what is uncertain in `note`.

Use the label given above for each equation. If an image isn't an
equation, return an empty `latex` with a note.

Return an EquationTranscription object.
