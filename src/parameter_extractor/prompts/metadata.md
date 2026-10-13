Extract bibliographic metadata for this paper: DOI (if printed on the page --
otherwise leave null, don't guess one), title, full author list in order,
publication year, and journal name.

This is usually unambiguous; if the DOI isn't visible in the provided text,
leave `paper_doi` null rather than inferring it -- a downstream step can look
it up from title+authors via CrossRef instead of risking a fabricated DOI.

Return a PaperMetadata object.

---
PAPER TEXT (title page / header):

{{PAPER_TEXT}}
