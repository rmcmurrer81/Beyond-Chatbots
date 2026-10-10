# Third-party notices and research-use boundaries

## Included Allen model file

`data/reference/allen_488386504_glif1.json` is an unmodified, 1,151-byte model-parameter file from the Allen Institute's official `GLIF_Teeter_et_al_2018` repository, `human_struc_data_dir/488386504_human/488386504_human_GLIF1_neuron_config.json`.

Source: https://github.com/AllenInstitute/GLIF_Teeter_et_al_2018

The upstream README identifies this directory as human data and says human data are not included in the associated manuscript's analysis. Do not claim this individual human cell was validated in that mouse-focused paper. The file's upstream Git blob is `1648ea1f6d51a6151578bca557d2e21a16e51393`.

Attribution: Allen Institute for Brain Science, Allen Cell Types Database; Corinne Teeter and collaborators, GLIF_Teeter_et_al_2018 research archive. Accessed 2026-09-29. Method context: Teeter et al., *Generalized leaky integrate-and-fire models classify multiple neuron types*, Nature Communications (2018) (as identified in the upstream README).

Read the applicable policies before any different use:

- Allen Terms of Use: https://alleninstitute.org/legal/terms-of-use
- Allen citation policy: https://alleninstitute.org/legal/citation-policy
- Archive licence: https://github.com/AllenInstitute/GLIF_Teeter_et_al_2018/blob/master/LICENSE

The terms and archive licence were reviewed for this private, noncommercial research prototype. Commercial use/distribution is NOT cleared. Do not silently package this source file or its derivatives into a product for sale. Public access does not mean unrestricted use, and keeping a repository private does not by itself make a commercial use noncommercial. Review or obtain permission for changed uses; this notice is not legal advice or a grant of additional rights.

## Upstream licence (retained)

Allen Institute Software License – This software license is the 2-clause BSD license
plus a third clause that prohibits redistribution for commercial purposes without further permission.

Copyright © 2018. Allen Institute. All rights reserved.

Redistribution and use in source and binary forms, with or without modification, are permitted provided that the
following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this list of conditions and the
following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the
following disclaimer in the documentation and/or other materials provided with the distribution.

3. Redistributions for commercial purposes are not permitted without the Allen Institute’s written permission.
For purposes of this license, commercial purposes is the incorporation of the Allen Institute's software into
anything for which you will charge fees or other compensation. Contact terms@alleninstitute.org for commercial
licensing opportunities.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE
USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

## Runner implementation

The NewBrain runner implements a restricted Euler GLIF1 experiment; it does not bundle AllenSDK. Method documentation and source were consulted and are recorded in the source ledger. Preserving the parameter file does not make NewBrain's event timing identical to the official SDK: independent parity testing remains pending.

BigBrain, H01 and The Virtual Brain are candidate references only. No dataset or software from those projects is redistributed in this starter. Their terms require separate review before importing or using them.
