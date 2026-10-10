import json, re, shutil
from pathlib import Path
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from xml.sax.saxutils import escape

ROOT=Path(__file__).resolve().parent/'_oct10_build';src=ROOT/'Beyond-Chatbots-Reorganized-October10-speaker-data.json';raw=json.loads(src.read_text())
titles=[
'NEWBRAIN — cover (unchanged)',
'BEYOND-CHATBOTS — scan the repository',
'The idea of artificial intelligence is old',
"Alan Turing's challenge",
'The first celebrated AI programs',
'ELIZA: conversation before modern AI',
'The ELIZA effect',
'A question raised by Caprica',
'AI did not begin with chatbots',
'What NewBrain is trying to build',
'One shared core, separate histories',
'All four delayed restarts passed review',
'Preservation is not the whole mind',
'Failures are part of the research',
'Whose memory is it?',
'Maya and the Avatar Builder',
'Vision, voice, and body feedback',
'Aster and IdeaForge: connected goals',
'Peter and Robert: earlier conversation kit',
'Why synthetic people?',
'What comes next — and where you can help',
'Questions & stay connected',
]
assert len(raw)==len(titles)==22
for x,t in zip(raw,titles):x['title']=t
pdfmetrics.registerFont(TTFont('DejaVu','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
pdfmetrics.registerFont(TTFont('DejaVu-Bold','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))
navy=colors.HexColor('#0A1D31');cyan=colors.HexColor('#118CA6');muted=colors.HexColor('#587287')
S={
'cover':ParagraphStyle('cover',fontName='DejaVu-Bold',fontSize=23,leading=30,textColor=navy,spaceAfter=9),
'sub':ParagraphStyle('sub',fontName='DejaVu',fontSize=11,leading=17,textColor=muted,spaceAfter=8),
'section':ParagraphStyle('section',fontName='DejaVu-Bold',fontSize=15,leading=20,textColor=navy,spaceBefore=13,spaceAfter=10),
'slide':ParagraphStyle('slide',fontName='DejaVu-Bold',fontSize=12.3,leading=18,textColor=navy,spaceBefore=11,spaceAfter=4),
'meta':ParagraphStyle('meta',fontName='DejaVu-Bold',fontSize=9,leading=14,textColor=cyan,spaceAfter=6),
'body':ParagraphStyle('body',fontName='DejaVu',fontSize=10,leading=16,textColor=colors.HexColor('#24394B'),spaceAfter=8),
'extra':ParagraphStyle('extra',fontName='DejaVu',fontSize=9.5,leading=15,textColor=colors.HexColor('#3B5970'),spaceAfter=5),
'answer':ParagraphStyle('answer',fontName='DejaVu',fontSize=9.4,leading=15,textColor=navy,spaceAfter=8),
}

def draw_frame(canvas,doc):
 canvas.saveState();w,h=letter
 canvas.setFillColor(navy);canvas.rect(0,h-18,w,18,fill=1,stroke=0)
 canvas.setFillColor(cyan);canvas.rect(0,h-22,w,4,fill=1,stroke=0)
 canvas.setFont('DejaVu',8);canvas.setFillColor(muted)
 canvas.drawString(40,27,'KIRA LABS  •  BEYOND CHATBOTS  •  OCTOBER 10, 2026')
 canvas.drawRightString(w-40,27,f'Page {doc.page}')
 canvas.restoreState()

def add(story,text,style='body'):
 story.append(Paragraph(escape(text).replace('\n','<br/>'),S[style]))

scriptpdf=ROOT/'Beyond-Chatbots-October10-Speaker-Script.pdf'
doc=SimpleDocTemplate(str(scriptpdf),pagesize=letter,rightMargin=44,leftMargin=44,topMargin=48,bottomMargin=47,title='Beyond Chatbots: October 10 timed speaker script',author='Kira Labs')
story=[]
add(story,'Beyond Chatbots — Timed Speaker Script','cover')
add(story,'Decentralized AI Day New York  •  October 10, 2026  •  2:30–3:00 p.m. ET','sub')
add(story,'Use the restructured 22-slide PowerPoint. Speak until about 2:55 p.m., then leave the final QR slide displayed for five minutes of Q&A. The timings are targets—rehearse once with a clock.','body')
for title,range_,summary in [
('PART 1','Slides 1–9 • 0:00–10:10','History of AI, Turing, ELIZA effect, Caprica, and your belief'),
('PART 2','Slides 10–15 • 10:10–18:00','NewBrain architecture, 4/4 preserved restarts, limits and lessons'),
('PART 3','Slides 16–20 • 18:00–23:15','Avatar Builder, Maya, vision, Aster, IdeaForge, Robert/Peter, purpose'),
('CLOSE','Slides 21–22 • 23:15–25:00','Research collaboration and final QR; then Q&A')]:
 story.append(Paragraph(f'<b>{title}</b> &nbsp; {escape(range_)}',S['meta']))
 add(story,summary,'body')
story.append(PageBreak())
for i,(d,title) in enumerate(zip(raw,titles)):
 if i in [0,9,15,20] and i!=0:
  # keep natural section breaks without forcing extra pages
  story.append(Spacer(1,10))
 tm=f"Slide {i+1:02d} — {d['start']} to {d['end']}"
 block=[Paragraph(escape(title),S['slide']),Paragraph(escape(tm),S['meta']),Paragraph(escape(d['script']),S['body'])]
 if d.get('extra'):block.append(Paragraph('<b>Presenter cue:</b> '+escape(d['extra']),S['extra']))
 block.append(HRFlowable(width='100%',thickness=.5,color=colors.HexColor('#C7D7E1'),spaceBefore=9,spaceAfter=5))
 story.append(KeepTogether(block))
story.append(Paragraph('Five-minute Q&A: 25:00–30:00',S['section']))
qna=[
('Is NewBrain like Qwen?','No. NewBrain is experimental learning and memory architecture research. The public code does not provide a qualified general Qwen replacement.'),
('What does 4/4 mean?','All four reported independent delayed-restart reviews accepted saved-state equivalence. Each retained 10,720 history records and matched 64 comparisons. That does not prove useful conversational recall.'),
('Is Maya born or conscious?','No accepted evidence establishes that. Maya is unfinished; learning, reliable recall, body movement, speech, and integration need more testing.'),
('Can I use the code tonight?','You can inspect and download the public research files. Some runnable parts require Python, Ollama, or other dependencies. Read each README: exported end-to-end tests remain pending.'),
('What failed?','The visual learner failed unfamiliar shape/color combinations, and an Aster memory study followed false records too often. Those failures guide the next tests.'),
('Can I try Peter or Robert?','The PreNewBrain package documents a local experimental chat and voice setup. Installation and speech have not been freshly qualified from this export; review privacy and voice-reference rights before using or redistributing assets.'),
('How can we help?','Reproduce a small test; propose rigorous holdouts; review source and provenance; or contact Kira Labs about compute, hardware, and collaboration.'),
]
for q,a in qna:
 story.append(Paragraph('<b>'+escape(q)+'</b>',S['meta']))
 story.append(Paragraph(escape(a),S['answer']))
story.append(Paragraph('Link to leave on screen: github.com/rmcmurrer81/Beyond-Chatbots',S['meta']))
doc.build(story,onFirstPage=draw_frame,onLaterPages=draw_frame)

# standalone plain text, self-contained
lines=['BEYOND CHATBOTS — OCTOBER 10, 2026','TIMED SPEAKER SCRIPT — 25-MINUTE TALK + 5 MINUTES Q&A','Repository: https://github.com/rmcmurrer81/Beyond-Chatbots','']
for i,(d,t) in enumerate(zip(raw,titles),1):
 lines.append(f"SLIDE {i:02d}: {t}")
 lines.append(f"ELAPSED TIME: {d['start']}–{d['end']}")
 lines.append(d['script'])
 if d.get('extra'):lines.append('PRESENTER CUE: '+d['extra'])
 lines.append('')
lines.append('FIVE MINUTES OF Q&A, 25:00–30:00')
for q,a in qna:lines+=['Q: '+q,'A: '+a,'']
(ROOT/'Beyond-Chatbots-October10-Speaker-Script.txt').write_text('\n'.join(lines),encoding='utf-8')

# two page run of show printable PDF with compact table and agenda
cuepdf=ROOT/'Beyond-Chatbots-October10-Quick-Cue-Sheet.pdf'
doc2=SimpleDocTemplate(str(cuepdf),pagesize=letter,rightMargin=42,leftMargin=42,topMargin=45,bottomMargin=40,title='Beyond Chatbots quick cue sheet',author='Kira Labs')
cues=[]
add(cues,'Beyond Chatbots — One-Glance Cue Sheet','cover')
add(cues,'25-minute talk • 5-minute Q&A • Slide 2 and the last slide have QR codes','sub')
add(cues,'PART 1 — HISTORY (0:00–10:10)','section')
quick={
1:'Introduce Kira Labs. This is research, not a finished Maya.',2:'Tell them to SCAN Beyond-Chatbots now; pause for codes.',
3:'Babbage → Lovelace → Turing → electronic computers.',4:'Turing asks how to judge a machine by conversation.',
5:'Dartmouth, Logic Theorist, General Problem Solver.',6:'ELIZA used patterns; illustrative terminal exchange.',
7:'ELIZA effect: perceived understanding ≠ tested capability.',8:'Caprica line + belief: machines CAN develop emotions and conscience.',
9:'Expert systems → Deep Blue → AlexNet → AlphaGo → foundation models.',
10:'NewBrain common engine vs identity-owned state.',11:'Kira, Lisa, Maya, Aster should not inherit each other’s autobiographies.',
12:'4/4 restart; 10,720 records; 64/64 pairs. State persistence only.',13:'No proof of general learning, recall, or consciousness.',
14:'Keep negative results: vision generalization and false memory.',15:'Owner/source/correction must remain distinct.',
16:'Show body as STATIC prototype, not completed moving Maya.',17:'Vision/voice/feedback are experiments, not full live senses.',
18:'Aster + IdeaForge have proposed interfaces, NOT live NewBrain.',19:'PreNewBrain Peter/Robert setup is experimental; inspect privacy/rights.',
20:'Why synthetic people matter to you personally.',21:'Next tests, independent reviewers, hardware and compute collaboration.',22:'Leave QR on screen for FIVE minutes of Q&A.',
}

def cue_table(entries):
 rows=[[Paragraph('<b>Slide</b>',S['meta']),Paragraph('<b>Elapsed</b>',S['meta']),Paragraph('<b>Short cue</b>',S['meta'])]]
 for i in entries:
  d=raw[i-1]
  rows.append([str(i),str(d['start']),Paragraph(escape(quick[i]),S['answer'])])
 t=Table(rows,colWidths=[45,76,408],repeatRows=1,hAlign='LEFT')
 t.setStyle(TableStyle([('BOX',(0,0),(-1,-1),.5,colors.HexColor('#D9E5EC')),('LINEBELOW',(0,0),(-1,0),1,cyan),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F3F8FC')]),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),3)]))
 return t
cues.append(cue_table(range(1,10)))
add(cues,'PART 2 — NEWBRAIN (10:10–18:00)','section')
cues.append(cue_table(range(10,16)))
cues.append(PageBreak())
add(cues,'PART 3 — BODY, APPS & PURPOSE (18:00–23:15)','section')
cues.append(cue_table(range(16,21)))
add(cues,'CLOSING (23:15–25:00)','section')
cues.append(cue_table(range(21,23)))
add(cues,'LAST FIVE MINUTES: QUESTIONS (25:00–30:00)','section')
add(cues,'Leave slide 22 visible. Keep answers short: state the outcome, one limitation, and the next test.','body')
add(cues,'If you run behind: briefly summarize slide 5 or slide 17, but do not rush the Caprica/ELIZA discussion or the 4/4 restart explanation.','body')
add(cues,'Two rehearsals before leaving: (1) scan the GitHub QR with your phone; (2) open the PDF slide backup and the final PPTX on the event laptop.','body')
add(cues,'GitHub: https://github.com/rmcmurrer81/Beyond-Chatbots','meta')
doc2.build(cues,onFirstPage=draw_frame,onLaterPages=draw_frame)

print('OUTPUTS')
for p in [ROOT/'Beyond-Chatbots-Reorganized-October10.pptx',scriptpdf,cuepdf,ROOT/'Beyond-Chatbots-October10-Speaker-Script.txt']:
 print(p,p.stat().st_size)