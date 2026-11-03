Extract bibliographic metadata for this paper: DOI (if printed on the page --
otherwise leave null, don't guess one), title, full author list in order,
publication year, and journal name.

This is usually unambiguous; if the DOI isn't visible in the provided text,
leave `paper_doi` null rather than inferring it -- a downstream step can look
it up from title+authors via CrossRef instead of risking a fabricated DOI.
The same for the year and journal: if the pages don't print them (a conference
abstract, a reprint without a header), give 0 for the year and '' for the
journal -- never infer them from the references or the content.

Return a PaperMetadata object.

{{PACK_RULES}}
---
PAPER TEXT (title page / header):

{{PAPER_TEXT}}
