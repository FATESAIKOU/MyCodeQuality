import json
from qmetrics import gitio


def parse_labels_copy(text):
    try:
        labels = json.loads(text)
    except ValueError:
        raise gitio.ToolError("labels_not_json", "--labels-json is not valid JSON")
    if not isinstance(labels, list) or not all(isinstance(x, str) for x in labels):
        raise gitio.ToolError("labels_bad_shape", "--labels-json must be a JSON array of strings")
    return labels
