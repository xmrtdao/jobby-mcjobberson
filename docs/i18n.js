/* Jobby i18n.
 *
 * Keyed by the English source string rather than by an id attribute. That is a
 * deliberate trade: the alternative is tagging 93 separate places in the markup
 * and a dictating robot adding "data-i18n" to a heading, which is a far bigger
 * diff and a far easier way to break the page. Keying by source means the
 * markup is untouched and the dictionary is the single place copy lives.
 *
 * The cost is that it cannot translate a sentence split across two elements,
 * and it cannot give two occurrences of the same string different renderings.
 * Neither happens in this copy, and _test_i18n.py fails on any English string
 * still on the page, so the cost cannot quietly start being paid.
 *
 * The agent's name is the exception, because it is a substitution rather than a
 * translation: "Jobby" alone becomes "Don Trabajo" in Spanish, and the rule that
 * Don is never used on its own is asserted in the test rather than trusted to
 * whoever edits this file next.
 */
(function () {
  'use strict';

  var ES = {
    // --- chrome and navigation
    'JM': 'DT',
    'Jobby McJobberson': 'Don Trabajo',
    'opportunity command center': 'centro de mando de oportunidades',
    'Funnel': 'Embudo',
    'Tracks': 'Rutas',
    'Audit': 'Auditoría',
    'Get started': 'Empezar',
    'Reading the market': 'Leyendo el mercado',
    'Pause animation': 'Pausar animación',
    'The animation repeats the four steps listed in the hero. It can be paused with the button beside it.': 'La animación repite los cuatro pasos de arriba. Puedes pausarla con el botón que tiene al lado.',

    // --- hero
    'A personal agent for your job search': 'Un agente personal para tu búsqueda de empleo',
    'Jobby does the work. You stay in charge.': 'Don Trabajo hace el trabajo. Tú tienes el control.',
    'Upload your resume and Jobby takes it from there: it reads the market, decides what is worth chasing, writes the outreach, fills in the applications, and comes back to you on the ones it will not guess at.':
      'Sube tu currículum y Don Trabajo sigue desde ahí: lee el mercado, decide qué merece la pena, escribe los mensajes de contacto, rellena las candidaturas y vuelve contigo con las que no se atreve a suponer.',
    'Reads your resume properly, then keeps it current as you correct it':
      'Lee tu currículum como es y lo mantiene al día según tú lo corrijas',
    'Sources the roles and writes the message for each one':
      'Busca los puestos y escribe el mensaje para cada uno',
    'Applies in your own browser, stopping at anything it cannot know':
      'Envía las candidaturas desde tu propio navegador y se detiene ante lo que no puede saber',

    // --- ingestion
    'Resume parsing': 'Lectura del currículum',
    'Drop a resume to build a source-derived profile':
      'Suelta un currículum para crear un perfil derivado del documento',
    'Drop your resume here': 'Suelta tu currículum aquí',
    'PDF, DOCX, or TXT · up to 10 MB': 'PDF, DOCX o TXT · hasta 10 MB',
    'Source-derived profile': 'Perfil derivado del documento',
    'Resume signals ready for review': 'Las señales de tu currículum, listas para revisar',
    'Only content found in the uploaded resume is shown.':
      'Solo se muestra lo que aparece en el currículum que has subido.',
    'Skills': 'Habilidades',
    'Related job fields': 'Áreas de empleo relacionadas',
    'Links': 'Enlaces',

    // --- dossier
    'AI dossier': 'Expediente de IA',
    'Building the candidate dossier': 'Creando el expediente del candidato',
    'Every field is taken from the resume itself. Anything the model could not confirm is listed under':
      'Cada dato procede del propio currículum. Lo que el modelo no ha podido confirmar aparece bajo',
    'Not stated in resume': 'No consta en el currículum',
    'rather than guessed, and anything it flagged for a second look is called out.':
      'en lugar de suponerlo, y todo lo que ha marcado para revisarlo se señala aparte.',
    'Starting': 'Empezando',
    'Read your details': 'Lee tus datos',
    'Pull the job history apart': 'Desmonta tu historial laboral',
    'Work out what it supports': 'Determina qué respalda',
    'Cross-check the dates': 'Contrasta las fechas',
    'Decide what it can claim': 'Decide qué puede afirmar',
    'Build your tracks and plan': 'Construye tus rutas y tu plan',
    'Usually under a minute. The dossier fills in on its own — you can keep reading.':
      'Normalmente menos de un minuto. El expediente se completa solo: puedes seguir leyendo.',
    'seconds so far, still working. The dossier fills in on its own.':
      'segundos hasta ahora, sigue trabajando. El expediente se completa solo.',

    // --- agent panel
    'Your agent': 'Tu agente',
    'Your career is the mission. Jobby works your corner: it reads the market, decides what to chase, writes the outreach, and keeps the pipeline moving until income is secured — and after.':
      'Tu carrera es la misión. Don Trabajo trabaja tu esquina: lee el mercado, decide qué perseguir, escribe los mensajes y mantiene viva la operación hasta que entrase el ingreso, y después.',
    'Mission': 'Misión',
    'Send outreach on my own': 'Enviar el contacto por mi cuenta',
    'Emergency stop': 'Parada de emergencia',
    'Upload a resume and Jobby takes it from there.':
      'Sube un currículum y Don Trabajo sigue desde ahí.',
    'Message Jobby': 'Escríbele a Don Trabajo',
    'Send': 'Enviar',
    'Jobby writes to your dossier when you tell it something. Every change is logged and you can see it below.':
      'Don Trabajo escribe en tu expediente cuando le cuentas algo. Cada cambio queda registrado y puedes verlo abajo.',
    'Google account': 'Cuenta de Google',
    'Checking…': 'Comprobando…',
    'Browse Drive': 'Ver Drive',
    'Check replies': 'Ver respuestas',
    'Disconnect': 'Desconectar',

    // --- panels
    'Your tracks': 'Tus rutas',
    'The plan': 'El plan',
    'What Jobby changed': 'Lo que cambió Don Trabajo',

    // --- what it does
    'What it actually does': 'Lo que hace de verdad',
    'Four things, done properly.': 'Cuatro cosas, bien hechas.',
    'Most job search tools are a template library and a button. Jobby holds your professional identity in one place, keeps it honest, and does the repetitive part of the search on your behalf.':
      'La mayoría de herramientas de búsqueda de empleo son una biblioteca de plantillas y un botón. Don Trabajo guarda tu identidad profesional en un solo sitio, la mantiene honesta y hace por ti la parte repetitiva de la búsqueda.',
    '01': '01',
    'One version of you': 'Una sola versión de ti',
    'Your resume, contact details, roles and skills live in a single dossier. Correct it once and every application after that is right. Tell Jobby something new in plain words and it writes it in, with your name on the change.':
      'Tu currículum, tus datos de contacto, tus puestos y tus habilidades viven en un único expediente. Corrígelo una vez y todas las candidaturas siguientes serán correctas. Cuéntale algo nuevo a Don Trabajo con tus palabras y lo escribe, con tu nombre en el cambio.',
    '02': '02',
    'It finds the work': 'Encuentra el trabajo',
    'Jobby searches for roles that fit what you have actually done, not keywords you once typed. It reads the posting, works out whether you are a real fit, and tells you plainly when you are not.':
      'Don Trabajo busca puestos que encajen con lo que has hecho de verdad, no con palabras clave que escribiste una vez. Lee la oferta, calcula si encajas de verdad y te lo dice con claridad cuando no encajas.',
    '03': '03',
    'It writes and sends': 'Escribe y envía',
    'A message written for that company and that role, from your dossier rather than from a template. You approve it, or you let Jobby send within a daily cap you set. Every message is logged.':
      'Un mensaje escrito para esa empresa y ese puesto, a partir de tu expediente y no de una plantilla. Tú lo apruebas, o dejas que Don Trabajo envíe dentro de un límite diario que marcas. Todos los mensajes quedan registrados.',
    '04': '04',
    'It applies for you': 'Envía tus candidaturas',
    'It fills in the form in your own browser and attaches your CV. If the form asks something your dossier does not answer, it stops and asks you instead of inventing an answer.':
      'Rellena el formulario en tu propio navegador y adjunta tu currículum. Si el formulario pregunta algo que tu expediente no responde, se detiene y te lo pregunta en vez de inventar una respuesta.',

    // --- tracks
    'Multi-Track Strategy': 'Estrategia multirruta',
    'Five tracks. One control plane.': 'Cinco rutas. Un solo panel de control.',
    'Track': 'Ruta',
    'Purpose': 'Objetivo',
    'Current status': 'Estado actual',
    'Track 1': 'Ruta 1',
    'High-Engagement Consultancy: Precision outreach for specialized advisory and fractional roles.':
      'Consultoría de alto nivel: contacto preciso para puestos de asesoría especializada y de tiempo parcial.',
    'Active recipient pipeline': 'Pipeline de destinatarios activos',
    'Track 2': 'Ruta 2',
    'Agile Contracting: Streamlined pipelines for temporary and short-term high-impact opportunities.':
      'Contratación ágil: procesos fluidos para oportunidades temporales y de alto impacto a corto plazo.',
    'Track 3': 'Ruta 3',
    'Strategic Placement: Orchestrated applications for permanent leadership and specialist roles.':
      'Colocación estratégica: candidaturas coordinadas para puestos de liderazgo permanente y de especialización.',
    'Track 4': 'Ruta 4',
    'ATS Automation: Boundary-aware automation for seamless application delivery via Page-Agent.':
      'Automatización de ATS: automatización consciente de los límites para enviar candidaturas sin fricción mediante Page-Agent.',
    'Page-agent boundary': 'Límite del agente de página',

    // --- integrity
    'The part that matters': 'Lo que importa',
    'It will not make something up.': 'No inventará nada.',
    'An agent that invents a fact about you is worse than no agent, because you find out at the interview. Jobby only states what your resume or your own corrections establish. Anything it cannot confirm is listed as unconfirmed, and anything that looks wrong on your resume is flagged so you can fix it.':
      'Un agente que inventa un dato sobre ti es peor que no tener agente, porque te enteras en la entrevista. Don Trabajo solo afirma lo que tu currículum o tus propias correcciones establecen. Lo que no puede confirmar aparece como no confirmado, y todo lo que en tu currículum parece equivocado queda marcado para que lo corrijas.',
    'No employer, title, date or number that is not in your record.':
      'Ningún empleador, puesto, fecha o cifra que no esté en tu expediente.',
    'Gaps stay gaps until you fill them — Jobby will not close them for you.':
      'Los huecos siguen siendo huecos hasta que tú los rellenes: Don Trabajo no los cerrará por ti.',
    'Every change to your profile is logged with who made it.':
      'Cada cambio en tu perfil queda registrado con quién lo hizo.',
    'Every message sent is kept, with the time and the recipient.':
      'Todos los mensajes enviados se guardan, con la hora y el destinatario.',
    'A daily send cap, and a stop button that takes effect immediately.':
      'Un límite diario de envíos y un botón de parada que surte efecto de inmediato.',

    // --- cta and footer
    'Start here': 'Empieza aquí',
    'Drop your resume in.': 'Suelta tu currículum.',
    'There is no account to create and no form to fill in. Upload your resume at the top of this page and Jobby will have read it, worked out which routes your background supports, and written you a plan before you have finished your coffee.':
      'No hay que crear una cuenta ni rellenar ningún formulario. Sube tu currículum arriba en esta página y Don Trabajo ya lo habrá leído, habrá calculado qué rutas sostiene tu experiencia y te habrá escrito un plan antes de que acabes el café.',
    'Go to the upload': 'Ir a la subida',
    'Jobby McJobberson — the professional preparation and orchestration layer.':
      'Don Trabajo: la capa de preparación profesional y coordinación.',
    'Repository': 'Repositorio',

    // --- the download, which the server has always supported and the page
    // never linked to until now.
    'Download your resume': 'Descargar tu currículum',
    'Print or save as PDF': 'Imprimir o guardar como PDF',

    // --- the dossier, which is the panel a candidate actually reads
    //
    // Its card titles and labels used to be hardcoded English in app.js. A panel
    // whose body is Spanish and whose headings are English reads as a bug rather
    // than as a missing translation, so they are here too.
    'Identity': 'Identidad',
    'Summary': 'Resumen',
    'Experience': 'Experiencia',
    // Added with the navigation, the dashboard headings and the floating chat.
    // Untranslated copy on a page with a language toggle is not a cosmetic miss:
    // it is a Spanish speaker clicking ES and still reading English.
    'Dashboard': 'Panel',
    'Employers': 'Empresas',
    'How you are being shown': 'Cómo se te está mostrando',
    'Email confirmed': 'Correo confirmado',
    'Do not have a resume?': '¿No tienes currículum?',
    'That is not a problem, and it is the more common starting point than it should be. Skip the upload box above and just start talking — tell Jobby what you did, what you are good at, what you want next. It writes it down as you go, tells you what is still missing rather than guessing at it, and builds the resume from your own words.': 'No es un problema, y es el punto de partida más común de lo que debería. Sáltate el cuadro de subida de arriba y empieza a hablar: cuéntale a Jobby lo que hiciste, lo que se te da bien, lo que quieres ahora. Lo va dejando por escrito según hablas, te dice lo que aúl falta en lugar de suponerlo, y construye el currículum con tus propias palabras.',
    'The conversation is in the corner of every page.': 'La conversación está en la esquina de cada página.',
    'It was a section here until it became clear that asking a question meant scrolling to find it and then navigating back to read the answer. Open the Jobby button at the bottom of the screen and it stays with you — on your dashboard, on this page, wherever you go.': 'Era una sección de esta página hasta que quedó claro que hacer una pregunta obligaba a desplazarse hasta encontrarla y luego volver para leer la respuesta. Abre el botón de Jobby al pie de la pantalla y te acompaña: en tu panel, en esta página, dondequiera que vayas.',
    // The verification panel, from the claim work. The send gate depends on
    // this panel being reachable, so its wording is load-bearing rather than
    // decorative.
    'Confirm your email and Jobby can apply to jobs on your behalf. It sends six digits to that inbox and you give them back here.': 'Confirma tu correo y Jobby podrá presentar solicitudes por ti. Manda seis dígitos a ese buzón y tú me los devuelves aquí.',
    'Your email address': 'Tu dirección de correo',
    'Send me a code': 'Mándame un código',
    'The six digits': 'Los seis dígitos',
    'Confirm': 'Confirmar',
    // The dossier panel, introduced with the five views. Describes only how the
    // product behaves, so it carries no claim that a mistranslation could falsify.
    'Every version of you': 'Todas tus versiones',
    'One dossier, read differently for every kind of work. A career that looks thin to a site recruiter and strong to an editor is not two careers — it is one, and the view is what changes. Nothing is invented to fill a gap; if a view has nothing to show, it says so.': 'Un solo expediente, leído de otra forma para cada tipo de trabajo. Una carrera que le parece floja a un reclutador de mina y sólida a un redactor no son dos carreras: es una, y lo que cambia es la lectura. No se inventa nada para rellenar un hueco; si una lectura no tiene nada que mostrar, lo dice.',
    // The jobs list. Added with the section, not after the coverage test
    // complained about it for the third time.
    'Home': 'Inicio',
    'Jobs': 'Empleos',
    'How it works': 'Cómo funciona',
    'Live from public feeds': 'En vivo desde fuentes públicas',
    'The jobs it is reading right now.': 'Los empleos que está leyendo ahora mismo.',
    'Every one of these came off a public job feed in the last few days, and every one is here with the feed it came from attached. Jobby has not read or checked any of them.': 'Todos estos salieron de una fuente de empleos pública en los últimos días, y cada uno viene con la fuente de la que salió. Jobby no ha leído ni verificado ninguno.',
    'Search jobs': 'Buscar empleos',
    'Search roles or employers': 'Busca puestos o empresas',
    'Filter by source': 'Filtrar por fuente',
    'Every source': 'Todas las fuentes',
    'Loading…': 'Cargando…',
    'Loading the board…': 'Cargando el tablón…',
    'Where these come from, and what each source is good for': 'De dónde vienen y para qué sirve cada fuente',
    'What each source contributed': 'Lo que aportó cada fuente',
    'Source': 'Fuente',
    'Employer stated': 'Empleador declarado',
    'From the title': 'Del título',
    'No employer': 'Sin empleador',
    'Location stated': 'Ubicación declarada',
    'Known problems with the board': 'Problemas conocidos del tablón',
    'Employer not stated': 'Empleador no declarado',
    'Location not stated': 'Ubicación no declarada',
    'No jobs on the board yet. The feeds are polled on a schedule; check back shortly.': 'Aún no hay empleos en el tablón. Las fuentes se consultan según un horario; vuelve pronto.',
    'Nothing on the board matches that. Try a broader word, or every source.': 'Nada en el tablón coincide. Prueba con algo más general o con todas las fuentes.',
    'Education': 'Formación',
    'Certifications': 'Certificaciones',
    'Extraction confidence': 'Confianza de la extracción',
    'Team size': 'Tamaño del equipo',
    'Name not stated': 'Nombre no consta',
    'None listed': 'Ninguno en la lista',
    'None inferred': 'Ninguno deducido',
    'Job fields': 'Áreas de empleo',
    'Domain expertise': 'Especialidad',
    'Suggested target roles': 'Puestos objetivo sugeridos',
    'Roles named in the resume': 'Puestos mencionados en el currículum',
    'Confirmed achievements': 'Logros confirmados',
    'Flagged for verification': 'Marcado para verificar',
    'Dossier for': 'Expediente de',
    'Dossier unavailable': 'Expediente no disponible',
    'The dossier could not be built.': 'No se ha podido crear el expediente.',

    // Status lines, which name the agent as well as saying something.
    // The key is the exact string app.js writes, punctuation included. One
    // of these ended in a full stop where the page uses U+2026, so it
    // matched nothing and the line stayed English with the suite green.
    'Resume parsed. Building the dossier…': 'Currículum leído. Creando el expediente…',
    'Resume parsed. Profile is ready for review.': 'Currículum leído. El perfil está listo para revisar.',
    'Parsing': 'Leyendo',
    'Working': 'Trabajando',
    'Dossier ready.': 'Expediente listo.',
    'Resume parsed. ': 'Currículum leído. ',
    'Dossier unavailable.': 'Expediente no disponible.',

    // --- the live agent panel, which renders values rather than copy
    //
    // The checkboxes beside these had been translated while the figures next
    // to them had not, which made it worse rather than better: a Spanish
    // panel with Spanish labels and English numbers reads as a half-finished
    // feature rather than an untranslated one. The figures are the same in
    // both languages, so these are templates with the numbers substituted
    // rather than a format table.
    '{n} of {total} tracks active': '{n} de {total} rutas activas',
    'No tracks active': 'Ninguna ruta activa',
    'Do not have a resume? That is not a problem, and it is the more common starting point than it should be. Skip the upload box above and just start talking — tell Jobby what you did, what you are good at, what you want next. It writes it down as you go, tells you what is still missing rather than guessing at it, and builds the resume from your own words.': '¿No tienes currículum? Eso no es un problema, y es el punto de partida más habitual de lo que debería ser. Sáltate el apartado de subir el currículum de arriba y empieza a hablar: cuéntale a Jobby lo que hiciste, en qué eres bueno y qué quieres hacer ahora. Lo irá anotando, te dirá lo que falta en lugar de suponerlo, y construirá el currículum con tus propias palabras.',
    'No resume? Good — start here. Tell me what you have done and I will write it down as we go, then turn it into a resume you can send. I will not invent anything you have not said.': '¿No tienes currículum? Perfecto, empieza aquí. Cuéntame lo que has hecho y lo iré anotando mientras hablamos, y luego lo convertiré en un currículum que puedas enviar. No inventaré nada que no me hayas dicho.',
    'Active': 'Activa',
    'Closed': 'Cerrada',
    'Available if you want it': 'Disponible si tú quieres',
    'FIFO & remote-site roles': 'Turnos FIFO y remoto',
    'ATS automation': 'Automatización ATS',
    'Full-time employment': 'Empleo a tiempo completo',
    'Temporary & contract': 'Temporal y contratos',
    'Contract consulting': 'Consultoría contractual',
    'About fly-in/fly-out work': 'Sobre el trabajo FIFO',
    'Opens on a stated willingness to rotate': 'Se activa si indicas que quieres rotar',
    '{used} of {cap} sends used in the last 24 hours':
      '{used} de {cap} envíos usados en las últimas 24 horas',
  };

  // Machine keys stay in English on purpose. They are stored in the database and
  // read by the relay, the renderer and the page agent, so translating them
  // would mean a migration and a field-by-field audit of every consumer. What
  // is translated is what a person reads.
  var EN = {};

  var DICT = { en: EN, es: ES };

  var AGENT_NAME = { en: 'Jobby McJobberson', es: 'Don Trabajo' };
  var AGENT_SHORT = { en: 'Jobby', es: 'Don Trabajo' };

  var current = 'en';

  function isSpanish() { return current === 'es'; }

  function pick(map) {
    return map && map[current] != null ? map[current] : map && map.en;
  }

  /** The agent's name in the active language. */
  function agentName() { return pick(AGENT_NAME); }
  function agentShort() { return pick(AGENT_SHORT); }

  /** Translate a string, falling through to itself. */
  function t(text) {
    if (current === 'en' || text == null) return text;
    var hit = DICT.es[text];
    return hit == null ? text : hit;
  }

  /** Apply the name substitution, so "Jobby" in a runtime string is renamed. */
  function name(text) {
    if (text == null) return text;
    if (current === 'en') return text;
    return String(text)
      .replace(/\bJobby McJobberson\b/g, AGENT_SHORT.es)
      .replace(/\bJobby\b/g, AGENT_SHORT.es);
  }

  /** Translate and rename in one step, for strings built at runtime. */
  function tn(text) { return name(t(text)); }

  var ATTRS = ['placeholder', 'title', 'aria-label', 'alt', 'aria-description'];

  function applyTo(root) {
    var walker = document.createTreeWalker(
      root, NodeFilter.SHOW_TEXT, {
        acceptNode: function (node) {
          if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
          var parent = node.parentElement;
          if (!parent) return NodeFilter.FILTER_REJECT;
          var tag = parent.tagName;
          // Never touch code, or the canvas/visually-hidden captions that
          // describe the animation in English for assistive tech: those are
            // written to be read aloud and are rewritten by their own rules.
          if (tag === 'CODE' || tag === 'SCRIPT' || tag === 'STYLE') {
            return NodeFilter.FILTER_REJECT;
          }
          return NodeFilter.FILTER_ACCEPT;
        }
      });
    var pending = [];
    var node;
    while ((node = walker.nextNode())) pending.push(node);
    pending.forEach(function (textNode) {
      var raw = textNode.nodeValue;
      var trimmed = raw.trim();
      var lead = raw.slice(0, raw.indexOf(trimmed));
      var tail = raw.slice(raw.indexOf(trimmed) + trimmed.length);
      var replaced = tn(trimmed);
      if (replaced !== trimmed) {
        textNode.nodeValue = lead + replaced + tail;
      }
    });

    // Attributes carry the strings a sighted user never sees but a screen
    // reader, a tooltip and a placeholder all do.
    root.querySelectorAll('[' + ATTRS.join('],[') + ']').forEach(function (el) {
      ATTRS.forEach(function (attr) {
        if (el.hasAttribute(attr)) {
          el.setAttribute(attr, tn(el.getAttribute(attr)));
        }
      });
    });
  }

  /**
   * Switching languages is not reversible by walking the same tree again: the
   * Spanish text is no longer a dictionary key. So the original text is stashed
   * on each node the first time, and switching back restores from that.
   */
  var STASH = '__i18nEn';

  function applyToStashed(root) {
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function (node) {
        return node.nodeValue && node.nodeValue.trim()
          ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      }
    });
    var nodes = [];
    var node;
    while ((node = walker.nextNode())) nodes.push(node);
    nodes.forEach(function (textNode) {
      if (textNode[STASH] == null) textNode[STASH] = textNode.nodeValue;
      var raw = textNode[STASH];
      var trimmed = raw.trim();
      var at = raw.indexOf(trimmed);
      textNode.nodeValue = current === 'en'
        ? raw
        : raw.slice(0, at) + tn(trimmed) + raw.slice(at + trimmed.length);
    });
    root.querySelectorAll('[' + ATTRS.join('],[') + ']').forEach(function (el) {
      ATTRS.forEach(function (attr) {
        var key = '__i18nEn_' + attr;
        if (el.hasAttribute(attr)) {
          if (el[key] == null) el[key] = el.getAttribute(attr);
          if (current !== 'en') el.setAttribute(attr, tn(el[key]));
          else el.setAttribute(attr, el[key]);
        }
      });
    });
  }

  function setLang(lang, opts) {
    current = lang === 'es' ? 'es' : 'en';
    document.documentElement.lang = current;
    try {
      window.localStorage.setItem('jobby-lang', current);
    } catch (e) { /* private mode: the toggle still works for this page */ }
    if (!(opts && opts.silent)) {
      applyToStashed(document.body);
      document.dispatchEvent(new CustomEvent('jobby:lang', {
        detail: { lang: current }
      }));
    }
    return current;
  }

  function getLang() {
    try {
      return window.localStorage.getItem('jobby-lang') === 'es' ? 'es' : 'en';
    } catch (e) {
      return 'en';
    }
  }

  /**
   * Translate a region that was built after the page's own pass ran.
   *
   * The track rows, the plan and the action list are all created in JavaScript
   * once the relay answers, which is after setLang() has already walked the
   * document. So they render in English on an otherwise Spanish page. Every
   * dynamic renderer calls this after building its rows.
   *
   * Exported deliberately. applyToStashed stashes the original on first sight,
   * which is what makes the toggle reversible, and hiding this kept the dynamic
   * half of the page permanently untranslated.
   */
  function applyI18nTo(root) {
    if (!root) return;
    applyToStashed(root);
  }

  window.JobbyI18n = {
    t: t,
    tn: tn,
    name: name,
    isSpanish: isSpanish,
    agentName: agentName,
    agentShort: agentShort,
    setLang: setLang,
    getLang: getLang,
    applyI18nTo: applyI18nTo,
    current: function () { return current; },
    dict: DICT,
  };
})();
