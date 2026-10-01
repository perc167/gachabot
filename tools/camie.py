"""Camie's tagger, which knows ten times as many characters as WD's.

The sweep identifies a character by asking a model who is in a frame, and it
can only ever find somebody the model was taught. WD's tagger knows 2,751
characters, which covers 216 of our top 500 - and the 284 it misses are not
random. Its vocabulary follows how often a character is drawn as fan art, so
it knows the girls of a show and not the boys: no Light Yagami, no Kakashi,
no Itachi, no Spike Spiegel.

Camie's tagger knows 26,968 characters, and covers 422 of the top 500. It is
856MB against 380MB and reads 512x512 rather than 448, so it is roughly three
times slower per frame. That is the trade: a sweep that takes three times as
long and can find twice as many people.

Same shape as the WD Tagger class on purpose - read(), alone(), characters -
so the sweep can take either one.

The model is not in the repo. It downloads on first use to .cache/.
"""
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, ".cache")
MODEL = os.path.join(CACHE_DIR, "camie-tagger.onnx")
META = os.path.join(CACHE_DIR, "camie-tagger-meta.json")

BASE = "https://huggingface.co/Camais03/camie-tagger/resolve/main/"
MODEL_URL = BASE + "model_initial.onnx"
META_URL = BASE + "model_initial_metadata.json"

SIZE = 512


class CamieTagger:
    """A picture in, Danbooru tags out - the same contract as Tagger."""

    def __init__(self, keep_above: float = 0.25):
        import numpy as np
        import onnxruntime as ort

        import fetch_episode_frames as sweep
        sweep.download(META_URL, META, "Camie tag list")
        sweep.download(MODEL_URL, MODEL, "Camie tagger model (856MB)")

        self.np = np
        self.keep_above = keep_above
        self.session = ort.InferenceSession(
            MODEL, providers=["CPUExecutionProvider"])
        self.input = self.session.get_inputs()[0]
        # The exported graph fixes a batch of four. Feeding one image four
        # times costs nothing we can avoid and keeps the shape it wants.
        shape = self.input.shape
        self.batch = shape[0] if isinstance(shape[0], int) else 1

        meta = json.load(io.open(META, encoding="utf-8"))
        order = meta["idx_to_tag"]
        self.names = [order[str(n)] for n in range(len(order))]
        kinds = meta["tag_to_category"]
        self.characters = {name for name in self.names
                           if kinds.get(name) == "character"}
        self.character_index = [n for n, name in enumerate(self.names)
                                if kinds.get(name) == "character"]
        self.general_index = [n for n, name in enumerate(self.names)
                              if kinds.get(name) == "general"]

    def prepare(self, image):
        """Square, 512, RGB, 0 to 1, channels first.

        Letterboxed onto white rather than stretched: a 16:9 frame squashed
        into a square is a different picture, and the frames are all 16:9.
        """
        from PIL import Image

        image = image.convert("RGBA")
        ground = Image.new("RGBA", image.size, (255, 255, 255, 255))
        image = Image.alpha_composite(ground, image).convert("RGB")
        width, height = image.size
        side = max(width, height)
        square = Image.new("RGB", (side, side), (255, 255, 255))
        square.paste(image, ((side - width) // 2, (side - height) // 2))
        square = square.resize((SIZE, SIZE), Image.BICUBIC)

        array = self.np.asarray(square, dtype=self.np.float32) / 255.0
        array = array.transpose(2, 0, 1)                  # HWC -> CHW
        batch = self.np.repeat(array[None], self.batch, axis=0)
        return batch

    def read(self, image) -> tuple:
        """(characters, other tags) the model sees, each with a confidence."""
        output = self.session.run(None, {self.input.name: self.prepare(image)})
        logits = output[0][0] if output[0].ndim > 1 else output[0]
        probs = 1.0 / (1.0 + self.np.exp(-logits))
        people = {self.names[n]: float(probs[n]) for n in self.character_index
                  if probs[n] >= self.keep_above}
        rest = {self.names[n]: float(probs[n]) for n in self.general_index
                if probs[n] >= self.keep_above}
        return people, rest

    def characters_in(self, image) -> dict:
        return self.read(image)[0]

    def alone(self, image, tag: str, reading=None) -> bool:
        """Is this a frame of `tag`, by themselves, with no lettering on it?

        The rules belong to the sweep, not to a model, so they are read from
        it rather than copied here.
        """
        import fetch_episode_frames as sweep

        people, rest = reading if reading else self.read(image)
        if people.get(tag, 0.0) < sweep.CONFIRM:
            return False
        if any(other != tag and value >= sweep.INTRUDER
               for other, value in people.items()):
            return False
        if any(rest.get(word, 0.0) >= sweep.BUSY for word in sweep.CROWD):
            return False
        if (any(rest.get(word, 0.0) >= sweep.BOTH for word in sweep.GIRLS)
                and any(rest.get(word, 0.0) >= sweep.BOTH
                        for word in sweep.BOYS)):
            return False
        if any(rest.get(word, 0.0) >= sweep.LETTERED
               for word in sweep.LETTERING):
            return False
        return True
