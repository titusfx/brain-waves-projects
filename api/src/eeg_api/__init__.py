"""EPOC+ live EEG workbench — backend.

The acquisition chain this wraps is verified on real hardware; see the repository
root ``AGENTS.md`` and ``eeg-vault/02-software/ud2016-crypto-crack.md``. This
package adds no new reverse engineering: it re-implements the same decoder the
``scripts/`` tools use, and puts a streaming API and a guided-protocol engine in
front of it.
"""

__version__ = "0.1.0"
