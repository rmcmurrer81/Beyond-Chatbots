"""Optional real-Tk geometry regression; no model, network, or speech devices."""
import os
import time
import json
import tempfile
from pathlib import Path
from PIL import Image
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import tkinter as tk
import ideaforge


@unittest.skipUnless(os.environ.get('DISPLAY'), 'Native Tk layout requires a display')
class NativeLayoutTests(unittest.TestCase):
    def test_minimum_layout_preserves_actions_with_long_labels(self):
        test = self
        class Root(tk.Tk):
            def mainloop(root):
                def children(widget):
                    for child in widget.winfo_children():
                        yield child
                        yield from children(child)
                widgets = list(children(root))
                for width, height in ((1180,700),(1000,700),(1500,850)):
                    root.wm_attributes('-zoomed', False)
                    root.update()
                    root.geometry(f'{width}x{height}')
                    for _ in range(50):
                        root.update()
                        if (root.winfo_width(),root.winfo_height()) == (width,height): break
                        time.sleep(.01)
                    test.assertEqual((root.winfo_width(),root.winfo_height()),(width,height))
                    for child in widgets:
                        try: value = str(child.cget('text'))
                        except tk.TclError: continue
                        if value.startswith('Current project:'):
                            child.configure(text='Current project: '+('Long descriptive invention name ' * 6))
                        elif value.startswith('No troubleshooting image') or value.startswith('Attached:'):
                            child.configure(text='Attached: '+('a-very-long-evidence-filename-' * 6)+'.png')
                    root.update_idletasks()
                    labels = ('Send','Research','Folder','Attach Image','Paste Screenshot','Clear',
                              'Start Hands-Free','Stop','Mute AI voice','My Equipment','Prototype','Simulation',
                              '3D Assembly Workspace','Use this','Source')
                    for label in labels:
                        button = next(w for w in widgets if 'text' in w.keys() and str(w.cget('text')) == label)
                        with test.subTest(size=(width,height),button=label):
                            test.assertTrue(button.winfo_ismapped())
                            test.assertGreaterEqual(button.winfo_width(),button.winfo_reqwidth())
                            test.assertGreaterEqual(button.winfo_height(),button.winfo_reqheight())
                            x,y=button.winfo_rootx(),button.winfo_rooty()
                            parent=button.master
                            while parent is not None:
                                test.assertGreaterEqual(x,parent.winfo_rootx())
                                test.assertGreaterEqual(y,parent.winfo_rooty())
                                test.assertLessEqual(x+button.winfo_width(),parent.winfo_rootx()+parent.winfo_width())
                                test.assertLessEqual(y+button.winfo_height(),parent.winfo_rooty()+parent.winfo_height())
                                parent=parent.master
                root.destroy()
        with tempfile.TemporaryDirectory() as directory:
            project=Path(directory)
            (project/'research').mkdir()
            (project/'project.json').write_text(json.dumps({'name':'Layout test project','plan':{}}))
            thumbnail=project/'thumbnail.png'
            Image.new('RGB',(320,200),'blue').save(thumbnail)
            (project/'research'/'gallery.json').write_text(json.dumps({'images':[{
                'index':1,'title':'Long gallery reference title ' * 8,
                'local_file':str(thumbnail),'page_url':'https://example.com/reference'}]}))
            chat=SimpleNamespace(model_name='layout-only fixture',current_project=project,current_project_name='Layout test project',
                                 research_manager=SimpleNamespace(event_callback=None,shutdown=lambda:None))
            with patch.object(ideaforge.tk,'Tk',Root), patch.object(ideaforge,'list_projects',return_value=[]):
                ideaforge.main(chat_factory=lambda:chat)



if __name__ == '__main__': unittest.main()
