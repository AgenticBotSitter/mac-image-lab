# Qwen-Image-2.1 Prompting Guide for Mac Image Lab

**Research date:** 2026-09-21
**Scope:** Qwen-Image-2.1 text-to-image on local ComfyUI/MPS.
**Primary sources:** [Qwen official README](https://github.com/QwenLM/Qwen-Image-2.1), [official T2I prompt-rewriter specification](https://github.com/QwenLM/Qwen-Image-2.1/blob/main/prompt_rewrite/prompts/system_prompt_t2i.txt), and [official ComfyUI image-edit template](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_qwen_image_2_1_image_edit.json).

## The short version

Write the prompt as a clear description of the finished frame, not as a loose pile of keywords. State the medium, subject, placement, background, material/texture, light, palette, and intended composition. Choose the aspect ratio and resolution in the UI rather than inserting `4K`, `2K`, or `16:9` into the prompt.

## A reliable text-to-image structure

Use this order:

1. **Medium and visual language** — photograph, editorial illustration, oil painting, flat vector, 3D render, poster, etc.
2. **Primary subject** — name it and give the important observable attributes.
3. **Placement and framing** — centred, lower right, close-up, full body, wide establishing shot, negative space on the left.
4. **Scene/background** — describe it specifically; avoid leaving the model to invent it.
5. **Materials and surface detail** — brushed metal, frosted glass, woven linen, rain-speckled pavement, visible brush strokes.
6. **Light** — source, direction, quality, highlights, and shadows.
7. **Composition and mood** — sparse, asymmetrical, quiet, energetic, balanced, warm, austere.
8. **Literal image text, if needed** — put the exact intended text in straight double quotes and describe where it appears.

### Strong prompt example

> A vertical editorial oil painting of a clear faceted glass vase filled with ivory peonies, pale blush roses, and small blue delphiniums, centered on a walnut table. The background is a softly weathered warm-ochre plaster wall with subdued olive shadows. Window light enters from the left, making soft highlights on the glass and deep natural shadows beneath the vase. Visible canvas grain and deliberate brush strokes give the flowers tactile texture. The composition is calm, balanced, and closely framed, with no readable text, logo, signature, or watermark.

### Weak prompt example

> Pretty flowers, beautiful, high quality, 8K, masterpiece.

It leaves the medium, arrangement, framing, palette, background, lighting, and materials undefined. `8K` and `masterpiece` do not replace concrete visual decisions.

## Best-known strengths

Qwen-Image-2.1 is explicitly designed for:

- **Detailed visual descriptions** with precise material, color, lighting, and composition information.
- **Typography and layout** when the intended visible strings are supplied exactly in quotes.
- **Transparent RGBA images.** Use the official wording: `This is an RGBA image with transparency. [description]. The image has alpha channel and the background is transparent.`
- **Reference-guided work and local edits**: the official model supports up to ten references, masks/annotations, subject/product identity preservation, background replacement, and local object changes. Mac Image Lab will expose this only after the Apple-MPS edit workflow is proven in an end-to-end test.
- **Native 2K-oriented aspect ratios.** The official recommended targets are 2048×2048 (1:1), 2400×1792 (4:3), 1792×2400 (3:4), 2528×1696 (3:2), 1696×2528 (2:3), 2752×1536 (16:9), and 1536×2752 (9:16). On this Mac, Maximum Native 2K must be used deliberately because it is slow.

## Known limitations and operator rules

- **A short vague brief causes the model to invent the missing frame.** Define the background, framing, light, and composition if they matter.
- **Do not use resolution labels as prompt instructions.** The official prompt rewriter treats `2K`, `4K`, and `8K` as quality requests, not aspect-ratio instructions. Set dimensions in the UI.
- **One prompt should describe one coherent image.** Avoid conflicting styles, camera angles, lighting conditions, or uncounted object lists.
- **Image text should be literal and limited.** Quote the exact words, describe their location and styling, and do not ask for dense small body copy. Inspect every output before using it.
- **Exact counts, identities, and small details can still drift.** Specify them clearly, then generate variations and select rather than assuming a first pass is final.
- **The Fast profile is for composition exploration, not final resolution.** Standard or Maximum Native should be chosen deliberately after a promising composition exists.
- **Reference/edit requests need preservation locks.** State the specific change first, then name what remains unchanged. Example: `Change only the background to a sunset beach. Preserve the subject's pose, facial identity, clothing, foreground lighting, and framing.`
- **For multiple reference images, name them explicitly as `<image1>`, `<image2>`, and so on.** The official workflow treats image 1 as the edit target and additional images as references.

## Practical presets

### Product/object study

> A square studio product photograph of [object], centered on [surface], against [specific background]. The object is [material, color, finish], with [specific physical details]. Soft [direction] light creates [shadow/highlight behavior]. The composition has [amount/location] of negative space. No readable text, logo, watermark, or extra objects.

### Portrait/editorial image

> A vertical editorial photograph of [adult subject], [pose and placement], wearing [garment/material/color]. The setting is [specific location/background]. [Direction and quality] lighting shapes [face/hair/clothing]. The image uses [lens/framing/depth-of-field language] and a [palette/mood] composition. No readable text, logo, or watermark.

### Transparent asset

> This is an RGBA image with transparency. A [specific object/character], [pose/material/color/detail]. The image has alpha channel and the background is transparent.

### Focused image edit, once enabled

> Change only [the named element] to [the exact desired result]. Preserve [the subject/pose/identity/clothing/framing/lighting/background elements that must remain fixed].

## Operating sequence

1. Start with Fast to test the composition.
2. Keep a good seed and prompt. Make a variation only when you want a new interpretation.
3. Use Standard for the chosen composition.
4. Use Maximum Native only when the output needs the native resolution and the longer MPS time is justified.
5. Inspect the result for text, anatomy, object count, surfaces, and unwanted marks before saving, filing, or archiving.

## Sources and licensing

This guidance summarizes public upstream technical documentation. Qwen-Image-2.1 is under the Qwen Research License; the Mac Image Lab application license does not grant model rights.
