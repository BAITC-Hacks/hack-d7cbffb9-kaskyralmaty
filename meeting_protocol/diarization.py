"""Разделение говорящих: ECAPA-эмбеддинги реплик Whisper и агломеративная кластеризация."""
from functools import lru_cache
from pathlib import Path

from .protocol import Segment

ECAPA = "speechbrain/spkrec-ecapa-voxceleb"
ECAPA_REVISION = "0f99f2d0ebe89ac095bcc5903c4dd8f72b367286"
SAMPLE_RATE = 16000
MIN_EMBED_SECONDS = 1.0     # shorter replicas are too noisy to seed clusters
# Cosine distance between cluster centroids above which clusters stay separate.
DISTANCE_THRESHOLD = 0.5  # tuned on the two case MP3s: 5 speakers each, as in the reference protocols


@lru_cache(maxsize=1)
def ecapa_model():
    import os
    from speechbrain.inference.speaker import EncoderClassifier
    savedir = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / f"ecapa-{ECAPA_REVISION[:12]}"
    return EncoderClassifier.from_hparams(source=ECAPA, revision=ECAPA_REVISION, savedir=str(savedir), run_opts={"device": "cuda"})


def cluster(embeddings, threshold: float = DISTANCE_THRESHOLD) -> list[int]:
    """Average-linkage agglomerative clustering on cosine distance; returns cluster index per row."""
    import numpy as np
    x = np.asarray(embeddings, dtype=np.float64)
    x = x / np.linalg.norm(x, axis=1, keepdims=True)
    clusters = [[i] for i in range(len(x))]
    while len(clusters) > 1:
        best, pair = None, None
        for a in range(len(clusters)):
            for b in range(a + 1, len(clusters)):
                distance = 1 - float((x[clusters[a]] @ x[clusters[b]].T).mean())
                if best is None or distance < best:
                    best, pair = distance, (a, b)
        if best > threshold:
            break
        a, b = pair
        clusters[a] += clusters.pop(b)
    labels = [0] * len(x)
    for index, members in enumerate(clusters):
        for member in members:
            labels[member] = index
    return labels


def diarize(audio: Path, segments: list[Segment]) -> list[Segment]:
    """Assign SPEAKER_N to every segment, numbered by first appearance."""
    import numpy as np
    import torch
    from faster_whisper.audio import decode_audio
    wave = decode_audio(str(audio), sampling_rate=SAMPLE_RATE)
    model = ecapa_model()

    def embed(segment: Segment):
        start, end = int(segment.start * SAMPLE_RATE), int(segment.end * SAMPLE_RATE)
        # Widen very short replicas to one second around their centre.
        missing = int(MIN_EMBED_SECONDS * SAMPLE_RATE) - (end - start)
        if missing > 0:
            start, end = max(0, start - missing // 2), min(len(wave), end + missing - missing // 2)
        with torch.inference_mode():
            vector = model.encode_batch(torch.from_numpy(wave[start:end]).unsqueeze(0).cuda())
        return vector.squeeze().float().cpu().numpy()

    vectors = np.stack([embed(s) for s in segments])
    long_ids = [i for i, s in enumerate(segments) if s.end - s.start >= MIN_EMBED_SECONDS] or list(range(len(segments)))
    seed_labels = cluster(vectors[long_ids])
    normed = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    centroids = []
    for label in sorted(set(seed_labels)):
        centroid = normed[[i for i, l in zip(long_ids, seed_labels) if l == label]].mean(axis=0)
        centroids.append(centroid / np.linalg.norm(centroid))
    nearest = (normed @ np.stack(centroids).T).argmax(axis=1)
    order: dict[int, str] = {}
    result = []
    for segment, label in zip(segments, nearest):
        name = order.setdefault(int(label), f"SPEAKER_{len(order) + 1}")
        result.append(segment.model_copy(update={"speaker": name}))
    return result
