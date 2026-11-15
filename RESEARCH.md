# Research context

EgoGaze explores a collection workflow for human visual attention alongside first-person imagery. The prototype implements acquisition, explicit quality metadata, inspection, and export. It has not trained or evaluated a robot model.

- **Look, Focus, Act** investigates gaze-informed foveated perception for robotic manipulation. It motivates retaining gaze and scene observations as potentially useful supervision. Its results are results of that research system, not measurements of EgoGaze. [Paper](https://arxiv.org/abs/2507.15833)
- **EgoMimic** studies joint learning from human egocentric and robot demonstrations. It motivates transferable human demonstration data while highlighting the additional robot data and policy-learning work needed beyond this recorder. [Project](https://egomimic.github.io/)
- **Ego4D gaze data** documents timestamps, gaze coordinates, and confidence. EgoGaze explicitly keeps confidence null because the current Raven API does not provide it, and preserves its own coordinate-space definition rather than implying format compatibility. [Gaze documentation](https://ego4d-data.org/docs/data/gaze/)
- **Ego-Exo4D gaze projection** documents the role of calibration in projecting eye gaze into imagery. EgoGaze therefore leaves real-camera projection unavailable until a valid device-specific mapping is established. [Projection tutorial](https://docs.ego-exo4d-data.org/tutorials/gaze/)

The included synthetic dataset demonstrates an input format for attention prediction. Behavioral cloning or a complete robot policy additionally requires action labels, suitable embodiment and timing treatment, and independent evaluation.
