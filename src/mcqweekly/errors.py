"""The two ToolError classes in use: taskquality and mcqreport each define their own. Catch both."""

from mcqreport.common import ToolError as MCQToolError
from taskquality.formats import ToolError as TQToolError

TOOL_ERRORS = (MCQToolError, TQToolError)
