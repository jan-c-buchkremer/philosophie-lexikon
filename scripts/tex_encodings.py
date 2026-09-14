"""The TeX Computer Modern font encodings, as 128-entry Unicode tables.

The formula fonts in the PDFs (`AdvP4C4E74`, `AdvP4C4E51`, `AdvP4C4E59`)
are Computer Modern `cmsy`, `cmmi` and `cmr` under new names; see
scripts/derive_tex_cmaps.py for the evidence. Their glyphs sit at the
positions Knuth gave them, and these tables say which character each
position is. Positions are the ORIGINAL font's, which is what a `/C<n>`
glyph name records -- the same fact derive_symbol_cmaps.py relies on for
ISO-8859-7 and Adobe Symbol.

Transcribed from the fonts' own layout (Knuth, "Computer Modern
Typefaces", and the tfm/enc files shipped with every TeX distribution).
Only positions that matter here were checked against rendered glyphs;
the rest follow the same source and are no less reliable, but a wrong
entry would be confidently wrong, so anything derived from these tables
is still verified on a contact sheet before it is written.

Where TeX distinguishes two shapes of one letter, the Unicode that means
the SHAPE is used: `\\phi` (straight) is U+03D5, `\\varphi` (loopy) is
U+03C6, `\\epsilon` (lunate) is U+03F5, `\\varepsilon` is U+03B5.
"""

# cmsy -- OMS, "math symbols"
OMS = (
    "−⋅×∗÷⋄±∓⊕⊖⊗⊘⊙○∘∙"   # 0x00  minus .. bullet
    "≍≡⊆⊇≤≥≼≽∼≈⊂⊃≪≫≺≻"   # 0x10  asymp .. succ
    "←→↑↓↔↗↘≃⇐⇒⇑⇓⇔↖↙∝"   # 0x20  arrows, simeq, propto
    "′∞∈∋△▽̸↦∀∃¬∅ℜℑ⊤⊥"    # 0x30  prime .. bot  (0x36 is the negation slash, combining)
    "ℵ𝒜ℬ𝒞𝒟ℰℱ𝒢ℋℐ𝒥𝒦ℒℳ𝒩𝒪"  # 0x40  aleph, calligraphic A-O
    "𝒫𝒬ℛ𝒮𝒯𝒰𝒱𝒲𝒳𝒴𝒵∪∩⊎∧∨"  # 0x50  calligraphic P-Z, cup .. vee
    "⊢⊣⌊⌋⌈⌉{}⟨⟩|‖↕⇕∖≀"    # 0x60  vdash .. wr
    "√∐∇∫⊔⊓⊑⊒§†‡¶♣♢♡♠"    # 0x70  surd .. spadesuit
)

# cmmi -- OML, "math italic"
OML = (
    "ΓΔΘΛΞΠΣΥΦΨΩαβγδϵ"   # 0x00  Greek capitals, alpha .. epsilon
    "ζηθικλμνξπρστυϕχ"   # 0x10  zeta .. chi
    "ψωεϑϖϱςφ↼↽⇀⇁↪↩▹◃"   # 0x20  psi, omega, variants, harpoons, triangles
    "0123456789.,<∕>⋆"    # 0x30  oldstyle digits, punctuation
    "∂𝐴𝐵𝐶𝐷𝐸𝐹𝐺𝐻𝐼𝐽𝐾𝐿𝑀𝑁𝑂"  # 0x40  partial, italic A-O
    "𝑃𝑄𝑅𝑆𝑇𝑈𝑉𝑊𝑋𝑌𝑍♭♮♯⌣⌢"  # 0x50  italic P-Z, flat .. frown
    "ℓ𝑎𝑏𝑐𝑑𝑒𝑓𝑔ℎ𝑖𝑗𝑘𝑙𝑚𝑛𝑜"  # 0x60  ell, italic a-o
    "𝑝𝑞𝑟𝑠𝑡𝑢𝑣𝑤𝑥𝑦𝑧ıȷ℘⃗⁀"   # 0x70  italic p-z, dotless, wp, vector, tie
)

# cmr -- OT1, "text"
OT1 = (
    "ΓΔΘΛΞΠΣΥΦΨΩﬀﬁﬂﬃﬄ"   # 0x00  Greek capitals, ligatures
    "ıȷ`´ˇ˘¯˚¸ßæœøÆŒØ"    # 0x10  dotless, accents, ligatures
    " !”#$%&’()*+,-./"    # 0x20
    "0123456789:;¡=¿?"    # 0x30
    "@ABCDEFGHIJKLMNO"    # 0x40
    "PQRSTUVWXYZ[“]^˙"    # 0x50  0x5E hat, 0x5F dot accent
    "‘abcdefghijklmno"    # 0x60
    "pqrstuvwxyz–—˝˜¨"    # 0x70  en dash, em dash, accents
)

TABLES = {"OMS": list(OMS), "OML": list(OML), "OT1": list(OT1)}
for _name, _table in TABLES.items():
    assert len(_table) == 128, (_name, len(_table))
