"""Fiction describes desired experience, never evidence that a mechanism is feasible."""


def manifest(project):
    text=(str(project.get('name',''))+' '+str(project.get('original_idea',''))).lower()
    groups=[]; inspiration=None
    if 'iron man' in text or 'ironman' in text:
        inspiration='Iron Man: fictional experience/requirements reference, not a physical specification.'
        groups=[('structure','Exoskeleton / mechanical frame',[],['What measured loads, joint axes and range of motion are required?']),
                ('power','Power and cooling',[],['What measured continuous/peak power, mass and heat budgets can real components meet?']),
                ('control','Local AI and control',['power'],['Which perception and control functions have reproducible evidence and safe fallbacks?']),
                ('display','HUD / user interface',['power','control'],['What field of view, latency and eye-safety constraints are documented?']),
                ('integration','Wearable integration',['structure','power','control','display'],['Are interfaces, mass distribution, emergency stop and thermal limits compatible?'])]
    elif 'holodeck' in text or 'star trek' in text:
        inspiration='Star Trek holodeck: fictional experience/requirements reference; solid light and unrestricted matter creation are not established.'
        groups=[('display','Immersive displays',[],['Which display methods provide measured field of view and viewing-volume performance?']),
                ('tracking','Tracking and spatial mapping',[],['What latency, accuracy and occlusion limits are measured?']),
                ('interaction','Haptic / physical interaction',['tracking'],['What forces and working volumes have real haptic systems demonstrated?']),
                ('content','Scene generation',['display','tracking'],['What scene/control latency is achievable with available compute?']),
                ('integration','Room-scale integration',['display','tracking','interaction','content'],['What space, power and participant-safety limits constrain the experience?'])]
    else:
        for index,name in enumerate(project.get('plan',{}).get('subsystems',[])[:24]):
            groups.append((f'subsystem_{index}',str(name)[:160],[],['What primary-source specifications, dimensions and interfaces are available?']))
    return {'goal':str(project.get('original_idea') or project.get('name') or 'Describe the intended outcome and measurable requirements.'),
            'origin':'project_plan','inspiration':inspiration,'status':'requirements_only_not_validated',
            'subsystems':[{'id':sid,'goal':goal,'depends_on':deps,'research_questions':questions,
                           'geometry_status':'missing_until_explicitly_supplied','evidence':[]} for sid,goal,deps,questions in groups],
            'evidence_policy':'Prefer original papers, university/lab publications and upstream repositories. Discovery metadata is not verified engineering evidence.'}


def validate_manifest(value):
    if not isinstance(value,dict) or not isinstance(value.get('goal',''),str):
        raise ValueError('Requirements need a text goal.')
    subsystems=value.get('subsystems',[])
    if not isinstance(subsystems,list) or len(subsystems)>32:
        raise ValueError('Requirements support at most 32 subsystems.')
    ids=set()
    for item in subsystems:
        if not isinstance(item,dict) or not isinstance(item.get('id'),str) or not item['id'] or item['id'] in ids:
            raise ValueError('Requirement subsystem IDs must be unique text.')
        ids.add(item['id'])
        if not isinstance(item.get('goal'),str): raise ValueError('Subsystem goals must be text.')
        for key in ('depends_on','research_questions'):
            if not isinstance(item.get(key,[]),list) or not all(isinstance(x,str) for x in item.get(key,[])):
                raise ValueError(key+' must be a list of text.')
    graph={item['id']:item.get('depends_on',[]) for item in subsystems}
    complete=set()
    def visit(key, stack):
        if key not in graph or key in stack: raise ValueError('Requirement dependencies are missing or cyclic.')
        if key in complete: return
        for dependency in graph[key]: visit(dependency,stack|{key})
        complete.add(key)
    for key in graph: visit(key,set())
    return value
