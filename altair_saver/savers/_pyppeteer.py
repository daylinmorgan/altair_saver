import asyncio
import base64
from typing import Any, Dict, List, Optional

import altair as alt
import nest_asyncio
from pyppeteer import launch

from altair_saver.types import JSONDict, MimebundleContent
from altair_saver.savers import Saver


class JavascriptError(RuntimeError):
    pass


CDN_URL = "https://cdn.jsdelivr.net/npm/{package}@{version}"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <title>Embedding Vega-Lite</title>
</head>
<body>
  <div id="vis"></div>
</body>
</html>
"""


EXTRACT_CODE = """
async (spec, embedOpt, format) => {
  if (format === "vega") {
    if (embedOpt.mode === "vega-lite") {
      vegaLite = typeof vegaLite === "undefined" ? vl : vegaLite;
      try {
        const compiled = vegaLite.compile(spec);
        spec = compiled.spec;
      } catch (error) {
        return { error: error.toString() };
      }
    }
    return { result: spec };
  }

  result = await vegaEmbed("#vis", spec, embedOpt)
    .then(function (result) {
      if (format === "png") {
        return result.view
          .toCanvas(embedOpt.scaleFactor || 1)
          .then(function (canvas) {
            return canvas.toDataURL("image/png");
          })
          .then(function (result) {
            return { result: result };
          })
          .catch(function (err) {
            console.error(err);
            return { error: err.toString() };
          });
      } else if (format === "svg") {
        return result.view
          .toSVG(embedOpt.scaleFactor || 1)
          .then(function (result) {
            return { result: result };
          })
          .catch(function (err) {
            console.error(err);
            return { error: err.toString() };
          });
      } else {
        const error = "Unrecognized format: " + format;
        return { error: error };
      }
    })
    .catch(function (err) {
      console.error(err);
      return { error: err.toString() };
    });

  return result;
}
"""


class PyppeteerSaver(Saver):
    """Save charts using pyppeteer."""

    valid_formats: Dict[str, List[str]] = {
        "vega": ["png", "svg"],
        "vega-lite": ["png", "svg", "vega"],
    }

    def __init__(
        self,
        spec: JSONDict,
        mode: Optional[str] = None,
        embed_options: Optional[JSONDict] = None,
        vega_version: str = alt.VEGA_VERSION,
        vegalite_version: str = alt.VEGALITE_VERSION,
        vegaembed_version: str = alt.VEGAEMBED_VERSION,
        scale_factor: Optional[float] = 1,
        **kwargs: Any,
    ) -> None:

        if scale_factor != 1:
            embed_options = embed_options or {}
            embed_options.setdefault("scaleFactor", scale_factor)
        super().__init__(
            spec=spec,
            mode=mode,
            embed_options=embed_options,
            vega_version=vega_version,
            vegalite_version=vegalite_version,
            vegaembed_version=vegaembed_version,
            **kwargs,
        )

    # TODO: implement offline mode similar to selenium saver

    async def _extract(self, fmt: str) -> MimebundleContent:
        browser = await launch(headless=True, args=["--no-sandbox"])
        # open a new tab in the browser
        page = await browser.newPage()
        # add URL to a new page and then open it
        await page.setContent(HTML_TEMPLATE)

        for package in ["vega", "vega-lite", "vega-embed"]:
            await page.addScriptTag(
                url=CDN_URL.format(
                    package=package, version=self._package_versions[package]
                ),
                type="text/javascript",
            )

        opt = self._embed_options.copy()
        opt["mode"] = self._mode
        result = await page.evaluate(EXTRACT_CODE, self._spec, opt, fmt)
        await page.close()
        await browser.close()

        if "error" in result:
            raise JavascriptError(result["error"])
        return result["result"]

    def _serialize(self, fmt: str, content_type: str) -> MimebundleContent:
        nest_asyncio.apply()
        out = asyncio.run(self._extract(fmt))

        if fmt == "png":
            assert isinstance(out, str)
            return base64.b64decode(out.split(",", 1)[1].encode())
        elif fmt == "svg":
            return out
        elif fmt == "vega":
            return out
        else:
            raise ValueError(f"Unrecognized format: {fmt}")
