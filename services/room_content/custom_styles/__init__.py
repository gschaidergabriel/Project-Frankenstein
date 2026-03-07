"""Custom art style plugins for Frank's Art Studio.

Frank can extend his painting capabilities by adding renderer files here.
Each file must define a single `render()` function with this signature:

    def render(*, palette, textures, q, qd, mood, epq, coherence,
               creative_intent, **kwargs) -> PIL.Image.Image:
        ...

Limits:
  - Max 10 custom style files
  - Max 500 lines per file
  - Filename becomes the style name (e.g. mosaic.py -> "mosaic")
  - Must return a PIL Image of CANVAS_SIZE x CANVAS_SIZE (1024x1024)
"""
