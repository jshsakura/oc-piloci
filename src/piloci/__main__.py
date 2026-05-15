"""Enable ``python -m piloci`` invocation.

Provided primarily as a Windows fallback when Smart App Control / WDAC
blocks the auto-generated ``oc-piloci.exe`` wrapper that uvx/pipx creates.
"""

from piloci.cli import main

if __name__ == "__main__":
    main()
