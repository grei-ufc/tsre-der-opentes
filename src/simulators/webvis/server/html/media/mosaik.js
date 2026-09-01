//
// Config
//
//width and height configure the window size of the visualization and DO NOT define
//the borders of the topology.
var width = window.innerWidth;
var height = window.innerHeight;
var sub_heights = {
    topology: height * 0.7,
    timeline: height * 0.3
}
var default_etype = {
    default: 0,
    min: 0,
    max: 0,
    unit: ''
}
// [OpenTES] Cor de cada série (fase) na linha do tempo. Fica no JS, e não só no
// CSS, porque é o JS que decide quantas séries existem — e um `path` sem estilo
// aplicado é preenchido de preto pelo navegador, o que transforma a curva numa
// mancha.
var series_colors = [
    'hsl(197, 60%, 40%)',
    'hsl(84, 55%, 33%)',
    'hsl(28, 75%, 45%)',
    'hsl(288, 45%, 45%)'
];

var topology_config = {
    // Nodes
    // [OpenTES] Era 6: um círculo de 12 px não comporta três setores
    // distinguíveis. O espaço existe — as ligações entre barras vizinhas ficam
    // com 49 px ou mais depois do ajuste de layout.
    node_r: 9,

    // border
    distance_to_border: 0.05,

    // Links
    // [OpenTES] Era 15: como a topologia não traz o comprimento das linhas,
    // toda aresta caía nesse padrão e os nós ficavam mais perto entre si do que
    // o próprio diâmetro deles — as arestas desapareciam sob os círculos.
    link_length: 45,  // default link length (if link.length == 0)
    link_factor: 100,  // factor for link length (if link.length > 0)

    // Force params
    force_default_charge: -10,
    force_charge: {
        pqbus: -10,
        refbus: -7.5
    },
    force_gravity: -0.12
}


//
// Global state :-)
//
var etypes = null;  // Entity types (will be set in setup());
// [OpenTES] Modo em que o nó mostra todas as fases de uma vez, uma por setor.
var SERIES_ALL = 'phases';
// [OpenTES] Qual grandeza colore os nós: SERIES_ALL, o índice de uma fase
// (0, 1, 2) ou uma agregação entre as fases presentes ('min', 'max', 'mean',
// 'spread').
var series = {
    labels: [],   // rótulos das fases, na ordem de `attrs`
    mode: SERIES_ALL
};
// [OpenTES] Preenchimento de uma fase que a barra não tem.
var ABSENT_FILL = '#ddd';
// [OpenTES] Escalas de cor no escopo global: o disco do nó e cada setor de fase
// precisam usar a mesma, senão as duas visões não seriam comparáveis.
var colorbars = {
    gr: d3.scaleLinear().range([0, 120]),     // HSL 'hue' de vermelho a verde
    rgr: d3.scaleLinear().range([-120, 120])  // de verde a vermelho a verde
};
var progressbar = ProgressBar();
var topology = Topology(topology_config);
var timeline = Timeline();
var svg = d3.select('#canvas').attr('width', width).attr('height', height);
var ws = make_websocket();


//
// Functions
//
/**
 * [OpenTES] Mostra na própria página um problema que impediria o desenho de
 * fazer sentido.
 *
 * Uma aresta SVG sem `stroke` não é desenhada e um `path` sem `fill: none` é
 * preenchido: quando a folha de estilo não é aplicada, o desenho sai errado sem
 * nenhum erro. Ficar em silêncio nesses casos foi o que custou mais tempo de
 * diagnóstico aqui, então agora eles aparecem.
 */
function report_problem(message) {
    console.error('[mosaik-web] ' + message);

    var box = document.getElementById('problems');
    if (!box) {
        box = document.createElement('div');
        box.id = 'problems';
        // Estilo embutido de propósito: este aviso precisa aparecer justamente
        // quando o CSS é que falhou.
        box.setAttribute('style', [
            'position:absolute', 'left:12px', 'bottom:12px', 'z-index:200',
            'max-width:60%', 'padding:8px 12px', 'border-radius:4px',
            'background:hsl(0,70%,96%)', 'border:1px solid hsl(0,60%,60%)',
            'color:hsl(0,60%,30%)', 'font:13px sans-serif'
        ].join(';'));
        document.body.appendChild(box);
    }

    var line = document.createElement('div');
    line.textContent = message;
    box.appendChild(line);
}

window.onerror = function(message, source, lineno) {
    report_problem('Erro de JavaScript: ' + message + ' (' + source + ':' + lineno + ')');
};

/**
 * [OpenTES] Confere o que o desenho precisa para ser legível e denuncia o que
 * faltar.
 */
function check_drawing(data) {
    if (!data.links.length) {
        report_problem(
            'A topologia chegou sem nenhuma ligação entre as barras. No cenário, '
            + 'confira `merge_types` (Line e Transformer) e as entidades criadas.'
        );
        return;
    }

    var unresolved = data.links.filter(function(link) {
        return !link.source || typeof link.source.x !== 'number'
            || !link.target || typeof link.target.x !== 'number';
    }).length;
    if (unresolved) {
        report_problem(unresolved + ' de ' + data.links.length
            + ' ligações ficaram sem extremos: elas não serão desenhadas.');
    }

    // O traço dos nós vem do main.css; se ele não foi aplicado, o desenho inteiro
    // depende de estilos que não existem.
    var node = svg.select('#topology .node').node();
    if (node && window.getComputedStyle(node).stroke === 'none') {
        report_problem(
            'A folha de estilo /media/main.css nao foi aplicada. Recarregue a '
            + 'pagina com Ctrl+Shift+R; se persistir, veja a aba Network do F12.'
        );
    }
}

/**
 * Setup the websocket.
 */
function make_websocket() {
    var callbacks = {
        setup_topology: setup,
        update_data: update
    };

    var ws = new WebSocket('ws://' + location.host + '/websocket');
    ws.onopen = function get_topology(evt) {
        ws.send('get_topology');
    };
    ws.onmessage = function dispatch(evt) {
        var msg = JSON.parse(evt.data);
        var msg_type = callbacks[msg[0]];
        if (msg_type) {
            msg_type(msg[1]);
        }
        else {
            console.log('Unknow message type: ' + msg[0]);
        }
    };
    ws.onclose = function(evt) {
        progressbar.set_progress(0);
    }

    return ws;
}

/**
 * Create and initialize the topology graph.
 *
 * *data* is an object with three attributes:
 *
 * - ``data.etypes`` contaisn the configuration for all entity types.
 * - ``data.nodes`` is a list of node objects for the topology
 * - ``data.links`` is a list of link objects for the topology
 */
function setup(data) {
    etypes = data.etypes;  // Set global variable
    progressbar.set_progress(0);
    make_series_selector(data.etypes);
    topology.create(data);
    timeline.init(data);
    check_drawing(data);
}

/**
 * [OpenTES] Atributos publicados por um tipo de entidade.
 *
 * ``attrs`` é a forma nova (uma entrada por fase); ``attr`` é a forma do
 * mosaik-web original e equivale a uma lista de um elemento.
 */
function etype_attrs(etype) {
    if (!etype) {
        return [];
    }
    if (etype.attrs && etype.attrs.length) {
        return etype.attrs;
    }
    return etype.attr ? [etype.attr] : [];
}

/**
 * [OpenTES] Cria a barra de botões que troca a fase mostrada no mapa de calor.
 *
 * Os rótulos vêm do tipo com mais atributos — numa rede trifásica, as três
 * fases da barra. Com um atributo só (o caso do mosaik-web original) não há o
 * que escolher e a barra não aparece.
 */
function make_series_selector(etypes) {
    var count = 0;

    Object.keys(etypes).forEach(function(type) {
        var attrs = etype_attrs(etypes[type]);
        if (attrs.length > count) {
            count = attrs.length;
            series.labels = etypes[type].series || attrs;
        }
    });
    series.labels = series.labels.slice(0, count);

    if (count < 2) {
        series.mode = 0;
        return;
    }

    // [OpenTES] '3φ' mostra as fases ao mesmo tempo, uma por setor do nó; os
    // demais modos desenham o nó como um disco único.
    var modes = [{key: SERIES_ALL, label: '3φ'}].concat(
        series.labels.map(function(label, i) {
            return {key: i, label: label};
        }),
        [
            {key: 'min', label: 'mín'},
            {key: 'max', label: 'máx'},
            {key: 'mean', label: 'méd'},
            {key: 'spread', label: 'desb'}
        ]
    );

    // A visão das três fases é a mais informativa, então é por ela que se
    // começa. A agregação declarada pelo cenário continua definindo o `value`
    // enviado pelo backend, que é o que os botões de agregação reproduzem.
    series.mode = SERIES_ALL;

    var buttons = d3.select('#controls').selectAll('div')
        .data(modes)
        .enter().append('div')
        .attr('class', function(d) {
            return 'series' + (d.key === series.mode ? ' active' : '');
        })
        .text(function(d) { return d.label; })
        .on('click', function(event, d) {
            series.mode = d.key;
            buttons.classed('active', function(b) { return b.key === series.mode; });
            topology.recolor();
        });
}

/**
 * [OpenTES] Valor de um nó na série selecionada.
 *
 * Devolve ``null`` quando não há leitura — inclusive quando a fase escolhida
 * não existe naquela barra, caso em que o OpenDSS reporta 0.0. Pintar esse zero
 * como tensão seria destacar como crítico justamente o nó que não tem a fase.
 */
/**
 * [OpenTES] Se o zero deve ser lido como "fase ausente" e não como um valor.
 *
 * Vale para grandezas por fase; num atributo único — uma potência, um tap —
 * zero é um valor legítimo.
 */
function ignores_zero(etype) {
    if (etype && etype.ignore_zero !== undefined) {
        return etype.ignore_zero;
    }
    return etype_attrs(etype).length > 1;
}

/**
 * [OpenTES] Fixa nas coordenadas do circuito os nós que as têm.
 *
 * As coordenadas chegam normalizadas em [0, 1], já com a proporção do
 * alimentador embutida. A caixa que elas ocupam é esticada até o limite do
 * canvas mantendo essa proporção — encaixá-las num quadrado, como fazia a
 * primeira versão, jogava fora a largura da tela e comprimia as barras a ponto
 * de os círculos cobrirem as linhas entre elas.
 */
function place_pinned_nodes(nodes) {
    var pinned = nodes.filter(function(node) {
        return typeof node.x === 'number' && typeof node.y === 'number';
    });

    if (!pinned.length) {
        return;
    }

    var x0 = d3.min(pinned, function(n) { return n.x; });
    var x1 = d3.max(pinned, function(n) { return n.x; });
    var y0 = d3.min(pinned, function(n) { return n.y; });
    var y1 = d3.max(pinned, function(n) { return n.y; });

    var pad = topology_config.node_r * 5;
    var avail_w = Math.max(width - 2 * pad, 1);
    var avail_h = Math.max(sub_heights.topology - 2 * pad, 1);

    var scale = Math.min(
        x1 > x0 ? avail_w / (x1 - x0) : Infinity,
        y1 > y0 ? avail_h / (y1 - y0) : Infinity
    );
    if (!isFinite(scale)) {
        scale = 0;  // todas as barras no mesmo ponto
    }

    var offset_x = (width - (x1 - x0) * scale) / 2;
    var offset_y = (sub_heights.topology - (y1 - y0) * scale) / 2;

    pinned.forEach(function(node) {
        node.pinned = true;
        node.x = node.fx = offset_x + (node.x - x0) * scale;
        node.y = node.fy = offset_y + (node.y - y0) * scale;
    });
}

/**
 * [OpenTES] Raio do nó, em pixels.
 *
 * O tipo pode pedir um raio próprio (``radius`` na configuração do etype), que
 * é como as cargas ficam menores que as barras às quais se ligam.
 */
function node_radius(node) {
    var etype = etypes[node.type];
    return (etype && etype.radius) || topology_config.node_r;
}

/**
 * [OpenTES] Espalha em volta da sua barra os nós que não têm coordenada.
 *
 * Sem isto o d3 inicializa todo nó sem posição numa espiral em torno da origem,
 * no canto superior esquerdo do canvas; a força da ligação puxa cada um na
 * direção da sua barra, mas a simulação esfria antes de chegar lá, e as cargas
 * acabam todas paradas do mesmo lado das barras. Partindo de um anel em volta
 * da âncora, o que resta às forças é só acomodar as sobreposições.
 *
 * Args:
 *     nodes: Nós da topologia; os fixados já têm ``x``/``y``.
 *     links: Arestas com ``source``/``target`` já resolvidos em objetos.
 */
function seed_free_nodes(nodes, links) {
    var anchors = new Map();

    function anchor(free, fixed) {
        if (!anchors.has(fixed)) {
            anchors.set(fixed, []);
        }
        anchors.get(fixed).push(free);
    }

    links.forEach(function(link) {
        if (link.source.pinned && !link.target.pinned) {
            anchor(link.target, link.source);
        }
        else if (link.target.pinned && !link.source.pinned) {
            anchor(link.source, link.target);
        }
    });

    anchors.forEach(function(free_nodes, fixed) {
        var count = free_nodes.length;
        free_nodes.forEach(function(node, i) {
            if (typeof node.x === 'number') {
                return;  // já semeado por outra âncora
            }
            // Distribuição regular no anel, deslocada meio setor: com uma única
            // carga ela fica acima da barra, e não sobre a linha que passa por
            // ela.
            var angle = (i + 0.5) * 2 * Math.PI / count;
            var radius = topology_config.link_length * (0.75 + 0.35 * ((i % 3) / 2));
            node.x = fixed.x + radius * Math.cos(angle);
            node.y = fixed.y + radius * Math.sin(angle);
        });
    });
}

function node_value(node) {
    var etype = etypes[node.type];
    var ignore_zero = ignores_zero(etype);
    var values = node.values || [];

    function usable(v) {
        return v !== null && v !== undefined && (!ignore_zero || v !== 0);
    }

    if (typeof series.mode === 'number') {
        var value = values[series.mode];
        return usable(value) ? value : null;
    }

    var present = values.filter(usable);
    if (!present.length) {
        return null;
    }

    switch (series.mode) {
        case 'min':
            return d3.min(present);
        case 'max':
            return d3.max(present);
        case 'mean':
            return d3.mean(present);
        case 'spread':
            return d3.max(present) - d3.min(present);
        default:
            return present[0];
    }
}

/**
 * [OpenTES] Valor de uma fase do nó, ou ``null`` se ela não existe na barra.
 */
function phase_value(node, index) {
    var etype = etypes[node.type];
    var value = (node.values || [])[index];

    if (value === null || value === undefined) {
        return null;
    }
    return (ignores_zero(etype) && value === 0) ? null : value;
}

/**
 * [OpenTES] Cor de uma leitura na escala do seu tipo de entidade.
 *
 * Extraída da coloração dos nós para que o disco (uma leitura só) e os setores
 * (uma leitura por fase) usem exatamente a mesma escala — senão as duas visões
 * do mesmo nó não seriam comparáveis.
 */
function heat_color(etype, value) {
    if (!etype || value === null || value === undefined) {
        return ABSENT_FILL;
    }

    var colorbar;
    if (series.mode === 'spread') {
        // Desequilíbrio não vive na escala de tensão: zero é o ideal e o topo é
        // o desvio que o cenário considera relevante.
        var spread_max = etype.spread_max || Math.abs(etype.max - etype.min) / 2 || 1;
        colorbar = colorbars.gr.domain([0, spread_max]);
        value = Math.min(spread_max, Math.max(0, value));
    }
    else {
        value = Math.min(etype.max, Math.max(etype.min, value));
        if (etype.min == 0) {
            // Positive values from [0, max]
            colorbar = colorbars.gr.domain([0, etype.max]);
        }
        else if (etype.max == 0) {
            // Negative values from [min, 0]
            colorbar = colorbars.gr.domain([0, etype.min]);
        }
        else {
            // Values in [min, max] with their center in (min + max) / 2
            colorbar = colorbars.rgr.domain([etype.min, etype.max]);
        }
    }

    var cval = colorbar(value);
    // Flip red-green to green-red (e.g, convert '0' to '120'):
    var range_max = colorbar.range()[1];
    cval = -1 * (Math.abs(cval) - range_max);

    return 'hsl(' + cval + ', 100%, 50%)';
}

/**
 * [OpenTES] Texto do tooltip do nó: o nome mais a leitura de cada fase.
 *
 * É o que diz qual fatia é qual fase — e dá o número, que a cor sozinha não dá.
 */
var format_value = d3.format('.4~f');

function node_title(node) {
    var etype = etypes[node.type];
    var attrs = etype_attrs(etype);
    if (attrs.length < 2) {
        return node.name;
    }

    var labels = (etype && etype.series) || attrs;
    var parts = [];
    for (var i = 0; i < attrs.length; i++) {
        var value = phase_value(node, i);
        parts.push(labels[i] + ': ' + (value === null ? '—' : format_value(value)));
    }

    var unit = (etype && etype.unit) ? '  ' + etype.unit : '';
    return node.name + '\n' + parts.join('   ') + unit;
}

/**
 * Update the progress bar, topology and (if needed) the timeline
 *
 * *data* is an object with two attributes:
 *
 * - ``data.progress`` is a number with the current sim. progress in [0, 100].
 * - ``data.nodes`` is a dict/object mapping node names to a new "value".
 */
function update(data) {
    progressbar.set_progress(data.progress);
    topology.update(data);
    timeline.update(data);
}


function ProgressBar() {
    var progress_bar = d3.select('#progress');
    var progress_scale = d3.scaleLinear()
        .domain([0, 100])
        .range([0, parseFloat(d3.select('html').style('width'))]);  // Convert width to a number

    return {
        set_progress: function set_progress(progress) {
            progress_bar.transition()
                .style('width', progress_scale(progress) + 'px');  // Add 'px' to the width value
        }
    };
}


function Topology(conf) {
    var self = {};
    self.disable_heatmap = false;

    /**
    * Create and initialize the topology graph.
    *
    * *data* is an object with three attributes:
    *
    * - ``data.etypes`` contaisn the configuration for all entity types.
    * - ``data.nodes`` is a list of node objects for the topology
    * - ``data.links`` is a list of link objects for the topology
    */
    function create(data) {

        self.disable_heatmap = data.disable_heatmap;

        // Set global etypes and initialize the ring buffer.
        var etypes = data.etypes;

        // [OpenTES] Cada aresta chega com os índices dos nós; aqui viram os
        // próprios objetos. O upstream deixava a resolução para o
        // `d3.forceLink().id(d => d.index)`, que depende de o d3 já ter numerado
        // os nós — e quando ela falha nada é avisado: `d.source.x` fica
        // `undefined` e a aresta é desenhada como um segmento de comprimento
        // zero, ou seja, some do desenho.
        data.links.forEach(function(link) {
            if (typeof link.source === 'number') {
                link.source = data.nodes[link.source];
            }
            if (typeof link.target === 'number') {
                link.target = data.nodes[link.target];
            }
        });

        place_pinned_nodes(data.nodes);
        seed_free_nodes(data.nodes, data.links);

        var anchored = data.nodes.some(function(node) { return node.pinned; });

        // Initialize force simulation
        var simulation = d3.forceSimulation(data.nodes)
            // [OpenTES] A distância é declarada aqui, na força que realmente tem
            // as arestas. O upstream a declarava numa segunda `forceLink()` sem
            // nenhuma aresta ('linkDistance', removida abaixo), de modo que o
            // acessor nunca era chamado e todas as ligações ficavam com a
            // distância padrão do d3.
            .force('link', d3.forceLink(data.links)
                .id(d => d.index)
                .strength(0.68)
                .distance(function(link) {
                    return link.length > 0 ? link.length * conf.link_factor
                                           : conf.link_length;
                }))
            .force('charge', d3.forceManyBody().strength(function(node) {
                var charge = conf.force_default_charge;
                if (node.type in etypes) {
                    // Update charge for type
                    var type_charge = conf.force_charge[etypes[node.type].cls];
                    if (typeof type_charge !== 'undefined') {
                        charge = type_charge;
                    }
                }
                return charge;
            }))
            // [OpenTES] As duas forças de centralização só entram quando o
            // desenho não tem âncoras. Com barras fixadas nas coordenadas do
            // circuito elas viram uma queda de braço que nunca converge: a
            // `forceCenter` desloca todos os nós a cada passo, os fixados voltam
            // para a sua coordenada, e o empurrão sobra inteiro para os nós
            // livres — que era o que arrastava as cargas todas para um lado.
            .force('center', anchored
                ? null
                : d3.forceCenter(width / 2, sub_heights.topology / 2))
            .force('collision', d3.forceCollide(function(node) {
                return node_radius(node) + 3;
            }))
            .force('boundary', boundaryForce(width, sub_heights.topology, conf.distance_to_border))
            .force('centering', anchored
                ? null
                : centeringForce(width / 2, sub_heights.topology / 2, 0.01))
            .on('tick', updatePositions)
            .alpha(3.6) // Set initial alpha to 1 to start simulation aggressively
            .alphaDecay(0.03); // Adjust alpha decay for a more gradual reduction in strength
    
        // Add circle and line elements for the topology
        var topology = svg.append('g')
            .attr('id', 'topology');
    
        var links = topology.selectAll('.link')
            .data(data.links)
            .enter().append('line')
            .attr('class', 'link')
            // [OpenTES] Traço embutido: uma `<line>` sem `stroke` simplesmente
            // não é desenhada, então a ligação entre as barras — a informação
            // mais básica do desenho — não pode depender de a folha de estilo
            // ter sido aplicada.
            .style('stroke', '#555')
            .style('stroke-width', '2px');
    
        // [OpenTES] Cada nó é um grupo, e não mais um círculo: dentro dele ficam
        // o disco (uma leitura só) e um setor por fase. Trocar de modo alterna
        // qual dos dois aparece, sem refazer o desenho. O traço e o
        // preenchimento continuam vindo do CSS aplicado ao grupo — em SVG os
        // dois são herdados pelos filhos.
        var nodes = topology.selectAll('.node')
            .data(data.nodes)
            .enter().append('g')
            .attr('class', function(node) {
                var cls = 'node';
                if (node.type in etypes && etypes[node.type].cls) {
                    cls += ' ' + etypes[node.type].cls;
                }
                if (node.pinned) {
                    cls += ' pinned';
                }
                return cls;
            })
            // O anel acompanha o tamanho do nó: a espessura fixa do CSS engolia
            // um nó pequeno.
            .style('stroke-width', function(node) {
                return Math.max(1.5, node_radius(node) / 3) + 'px';
            })
            .on('click', function(event, d) {
                timeline.create(d, d3.select(this));
            })
            .call(d3.drag()
                .on('start', dragstarted)
                .on('drag', dragged)
                .on('end', dragended));

        nodes.append('title').text(function(node) {
            return node.name;
        });

        nodes.append('circle')
            .attr('class', 'disc')
            .attr('r', node_radius);

        nodes.each(function(node) {
            var attrs = etype_attrs(etypes[node.type]);
            if (attrs.length < 2) {
                return;  // uma grandeza só: o disco já a representa inteira
            }

            var arc = d3.arc().innerRadius(0).outerRadius(node_radius(node));
            var slice = 2 * Math.PI / attrs.length;
            var group = d3.select(this);
            for (var i = 0; i < attrs.length; i++) {
                group.append('path')
                    .attr('class', 'sector s' + i)
                    // Meia fatia de deslocamento para a primeira fase ficar
                    // centrada no topo do nó.
                    .attr('d', arc({
                        startAngle: i * slice - slice / 2,
                        endAngle: (i + 1) * slice - slice / 2
                    }));
            }

            // Contorno por cima das fatias: é ele que mantém o anel da cor do
            // tipo (carga, gerador, regulador) também na visão por fase, sem
            // engrossar as divisórias entre as fatias.
            group.append('circle')
                .attr('class', 'outline')
                .attr('r', node_radius(node))
                .style('fill', 'none');
        });

        // Custom centering force
        function centeringForce(centerX, centerY, strength) {
            return function(alpha) {
                data.nodes.forEach(function(node) {
                    node.vx += (centerX - node.x) * strength * alpha;
                    node.vy += (centerY - node.y) * strength * alpha;
                });
            };
        }

        // Custom force to keep nodes within the buffered bounds
        function boundaryForce(width, height, distanceToBorder) {
            var bufferX = width * distanceToBorder;
            var bufferY = height * distanceToBorder;
            return function(alpha) {
                data.nodes.forEach(function(node) {
                    // Apply buffer zone constraints
                    if (node.x < bufferX) node.x = bufferX;
                    if (node.y < bufferY) node.y = bufferY;
                    if (node.x > width - bufferX) node.x = width - bufferX;
                    if (node.y > height - bufferY) node.y = height - bufferY;
                });
            };
        }
    
        function updatePositions() {
            links.attr('x1', function(d) { return d.source.x; })
                .attr('y1', function(d) { return d.source.y; })
                .attr('x2', function(d) { return d.target.x; })
                .attr('y2', function(d) { return d.target.y; });
    
            // [OpenTES] O nó virou um grupo: posiciona-se por transform.
            nodes.attr('transform', function(d) {
                return 'translate(' + d.x + ', ' + d.y + ')';
            });
        }
    
        function dragstarted(event, d) {
            if (!event.active) simulation.alphaTarget(0.15).restart();
            d.fx = d.x;
            d.fy = d.y;
        }
    
        function dragged(event, d) {
            d.fx = event.x;
            d.fy = event.y;
        }
    
        function dragended(event, d) {
            if (!event.active) simulation.alphaTarget(0);
            // [OpenTES] Um nó preso à coordenada real do circuito continua preso
            // onde o usuário o largou; soltá-lo devolveria ao layout de forças um
            // nó cuja posição é informação do circuito, não do desenho.
            if (!d.pinned) {
                d.fx = null;
                d.fy = null;
            }
        }
    
        make_legend(etypes, conf);
    }
    
    /**
    * Create a legend for the various node types.
    *
    * *etypes* is "data.etypes" the same as in "setup()".
    */
    function make_legend(etypes, conf) {
        var node_r = conf.node_r;
        var legend = svg.append('g')
            .attr('id', 'topology_legend')
            .attr('class', 'legend')
            .attr('transform', 'translate(30, 30)');
    
        // Use Object.entries instead of d3.entries
        var items = Object.entries(etypes)
            .sort(function(a, b) { return a[0] > b[0]; });
    
        var li = legend.selectAll('g')
                    .data(items)
                .enter().append('g')
                    .attr('transform', function(d, i) {
                        return 'translate(0, ' + (i * node_r * 4) + ')';
                    });
                    
        li.append('circle')
            .attr('cx', 0)
            .attr('cy', 0)
            // [OpenTES] O mesmo raio que o tipo tem no desenho, para a legenda
            // também mostrar a diferença de tamanho entre barras e cargas.
            .attr('r', function(d) { return d[1].radius || node_r; })
            .attr('class', function(d) { return 'node ' + d[1].cls; });
            
        li.append('text')
            .attr('x', node_r * 3.5)
            .attr('y', node_r)
            .text(function(d) { return d[0]; });
    }
    

    /**
    * Update visualization with new data
    */
    function update(data) {
        if (self.disable_heatmap === true) {
            return;
        }
        // Update node data and the ring buffer.
        var node_data = data.node_data[data.node_data.length - 1];
        svg.selectAll('#topology .node').data().forEach(function(node) {
            var incoming = node_data[node.name];
            if (!incoming) {
                return;
            }
            node.value = incoming.value;
            // [OpenTES] Um valor por atributo (as três fases, tipicamente). O
            // backend mais antigo mandava só o agregado.
            node.values = incoming.values || [incoming.value];
        });

        recolor();
    }

    /**
    * [OpenTES] Repinta os nós com a série selecionada, sem esperar novos dados.
    *
    * No modo '3φ' cada setor recebe a cor da sua própria fase e o disco fica
    * escondido; nos demais modos é o contrário. Como os dois já existem no
    * desenho, trocar de modo é só alternar a visibilidade.
    */
    function recolor() {
        if (self.disable_heatmap === true) {
            return;
        }

        svg.selectAll('#topology .node').each(function(node) {
            var group = d3.select(this);
            var etype = etypes[node.type];
            var sectors = group.selectAll('.sector');
            var by_phase = series.mode === SERIES_ALL && !sectors.empty();

            group.select('title').text(node_title(node));

            var value = node_value(node);
            group.select('.disc')
                .style('display', by_phase ? 'none' : null)
                .style('fill', heat_color(etype, value))
                .classed('absent', etype !== undefined && value === null);

            sectors
                .style('display', by_phase ? null : 'none')
                .each(function(_, index) {
                    var phase = phase_value(node, index);
                    d3.select(this)
                        .style('fill', heat_color(etype, phase))
                        .classed('absent', phase === null);
                });
        });
    }

    return {
        create: create,
        update: update,
        recolor: recolor
    };
}


/**
 * Animated time line of a node's data.
 *
 * Inspired by http://bl.ocks.org/mbostock/1642874
 */
function Timeline() {
    var self = {};
    self.start_date = null;
    self.update_interval = null;
    self.timeline_backlog = null;
    self.time = 0;
    self.timeline_node = null;
    self.timeline_circle = null; // Highlighted circle element of the topo.
    self.backlog_data = {};
    self.timeline_buf = [];  // Buffer for the currently active timeline
    self.ignore_zero = false;  // [OpenTES] Regra de zero do nó aberto

    // Margin and size of the actual drawing area
    self.m = {top: 20, right: 20, bottom: 30, left: 110};
    self.w = width - self.m.left - self.m.right;
    self.h = sub_heights.timeline - self.m.top - self.m.bottom;

    // Scale to map data values to the pixel grid
    self.x = d3.scaleTime().range([0, self.w]);
    self.y = d3.scaleLinear().range([self.h, 0]);

    // Axes
    self.x_axis = null;  // Will be the svg element
    self.y_axis = null;  // Will be the svg element
    self.y_pos = null;  // Vertical position of the x-axis
    
    // Custom multi-format function
    function multiFormat(date) {
        return (d3.timeSecond(date) < date ? d3.timeFormat(".%L")
            : d3.timeMinute(date) < date ? d3.timeFormat(":%S")
            : d3.timeHour(date) < date ? d3.timeFormat("%H:%M")
            : d3.timeDay(date) < date ? d3.timeFormat("%H:%M")
            : d3.timeMonth(date) < date ? (d3.timeWeek(date) < date ? d3.timeFormat("%a %d") : d3.timeFormat("%b %d"))
            : d3.timeYear(date) < date ? d3.timeFormat("%B")
            : d3.timeFormat("%Y"))(date);
    }

    self.make_x_axis = d3.axisBottom(self.x)
        .tickFormat(multiFormat);
    
    self.make_y_axis = d3.axisLeft(self.y).ticks(5);

    // Function mapping data to (x, y) coordinates in the plot, set in init().
    self.make_line = null;

    /**
     * Return the domain based on the current time. This will be like
     * [current_time - backlog_size, current_time].
     */
    function get_domain() {
        var domain_left = self.time - (self.timeline_backlog * self.update_interval);
        var domain_right = self.time;
        return [domain_left, domain_right];
    }


    /**
     * Create the ring buffers for node data. This is done once when the
     * app starts.
     */
    function init(data) {
        self.start_date = new Date(data.start_date);
        self.update_interval = data.update_interval * 1000;  // milliseconds
        // [OpenTES] O backlog é contado em pontos, não em minutos. O upstream
        // multiplicava as horas por 60, o que só dá as horas pedidas quando o
        // passo é de 1 minuto (o do demo do mosaik). Com o passo de 5 min dos
        // nossos cenários a janela virava 5 dias, e as amostras existentes
        // ficavam espremidas contra a borda direita — a curva sumia.
        self.timeline_backlog = Math.max(
            1,
            Math.round(data.timeline_hours * 3600 / data.update_interval)
        );
        data.nodes.forEach(function(node) {
            self.backlog_data[node.name] = new RingBuffer(self.timeline_backlog + 1, null);
        });
        self.make_line = d3.line()
            // [OpenTES] A fase que a barra não tem chega como 0.0 (ou nula):
            // interromper a linha é o que impede uma fase inexistente de virar
            // uma curva rente ao eixo. `self.ignore_zero` acompanha o nó aberto,
            // porque num atributo único o zero é um valor de verdade.
            .defined(function(d) { return is_plottable(d); })
            .x(function(d, i) {
                return self.x(self.time - ((self.timeline_backlog - i) * self.update_interval));
            })
            .y(function(d) {
                return self.y(d);
            });
    }

    /**
     * [OpenTES] Um ponto entra na curva e no domínio do eixo Y?
     */
    function is_plottable(d) {
        if (d === null || d === undefined) {
            return false;
        }
        return !self.ignore_zero || d !== 0;
    }

    /**
     * [OpenTES] Valores plotáveis de uma série, para calcular o domínio do eixo Y.
     */
    function plottable(values) {
        return values.filter(is_plottable);
    }

    /**
     * [OpenTES] Extrai a série *index* do buffer circular do nó.
     *
     * O buffer guarda, por instante, o vetor de valores do nó (uma entrada por
     * fase); cada curva precisa do seu recorte.
     */
    function series_data(node_name, index) {
        return self.backlog_data[node_name].data().map(function(values) {
            if (values === null || values === undefined) {
                return null;
            }
            return Array.isArray(values) ? values[index] : values;
        });
    }
    

    /**
     * Create axes for the timeline. This is done at every click on a node
     * in the topology graph.
     *
     * *node* is a node object from the topology.
     */
    function create(node, circle) {
        svg.selectAll('#timeline').remove();
        if (self.timeline_circle) {
            self.timeline_circle.classed('highlight', false);
        }
        if (self.timeline_node == node.name) {
            self.timeline_node = null;
            self.timeline_circle = null;
            return;
        }
        self.timeline_node = node.name;
        self.timeline_circle = circle.classed('highlight', true);

        var etype_conf = (node.type in etypes) ? etypes[node.type] :
                                                 default_etype;
        // [OpenTES] Regra de zero do nó aberto, usada ao desenhar as curvas.
        self.ignore_zero = ignores_zero(etypes[node.type]);

        var min = etype_conf.min;
        var max = etype_conf.max;
        self.x.domain(get_domain());
        self.y.domain([min, max]);

        // Add an SVG element with the desired dimensions and margin.
        var timeline = svg.append('g')
            .attr('id', 'timeline')
            .attr('class', 'timeline')
            .attr('transform', 'translate(0, ' + sub_heights.topology + ')')
            .attr('width', self.w + self.m.left + self.m.right)
            .attr('height', self.h + self.m.top + self.m.bottom);

        // Title
        var title = node.name;
        if (!(node.type in etypes)) {
            title += ' [not configured]';
        }
        timeline.append('text')
            .attr('class', 'label')
            .attr('text-anchor', 'middle')
            .attr('x', self.m.left + self.w / 2)
            .attr('y', '1em')
            .text(title);

        var graph = timeline.append('g')
            .attr('transform',
                  'translate(' + self.m.left + ', ' + self.m.top + ')');

        // Clip path for animated timeline
        graph.append('defs').append('clipPath')
                .attr('id', 'clip')
            .append('rect')
                .attr('width', self.w)
                .attr('height', self.h);

        // Append the x-axis
        if (min == 0 || max == 0) {
            self.y_pos = 0;
        }
        else {
            // Vertically center x-axis, e.g. for node voltages.
            self.y_pos = (min + max) / 2;
        }
        self.x_axis = graph.append('g')
            .attr('class', 'x axis')
            .attr('transform', 'translate(0, ' + self.y(self.y_pos) + ')')
            .call(self.make_x_axis);

        // Append the y-axis
        self.y_axis = graph.append('g')
                .attr('class', 'y axis')
                .call(self.make_y_axis);
        self.y_axis.append('text')
                .attr('class', 'label')
                .attr('text-anchor', 'end')
                .attr('x', 0)
                .attr('dx', -60)
                .attr('y', self.h / 2)
                .attr('dy', '.32em')  // or: #y_axis -> g[2/5] -> text.dy
                .text(etype_conf.unit);

        // [OpenTES] Uma curva por atributo do tipo — as três fases da barra, no
        // caso trifásico. Com um atributo só o desenho é o do mosaik-web
        // original.
        var attrs = etype_attrs(etype_conf);
        var labels = etype_conf.series || attrs;
        var plot = graph.append('g').attr('clip-path', 'url(#clip)');

        for (var i = 0; i < Math.max(attrs.length, 1); i++) {
            plot.append('path')
                .datum(series_data(node.name, i))
                .attr('class', 'line s' + i)
                // Explícito de propósito: sem `fill`, o navegador preenche o
                // path de preto e a curva vira uma área entre o primeiro e o
                // último ponto.
                .style('fill', 'none')
                .style('stroke', series_colors[i % series_colors.length])
                .attr('d', self.make_line);
        }

        if (attrs.length > 1) {
            make_series_legend(timeline, labels);
        }

        tick();
    }

    /**
     * [OpenTES] Legenda das curvas, com a mesma cor que a linha correspondente.
     */
    function make_series_legend(timeline, labels) {
        var swatch = 18;   // comprimento do traço colorido
        var spacing = 4;   // do traço até o seu rótulo
        var gap = 16;      // entre um item e o próximo

        var legend = timeline.append('g').attr('class', 'series-legend');

        var items = legend.selectAll('g')
            .data(labels)
            .enter().append('g');

        items.append('line')
            .attr('class', function(d, i) { return 'legend-item s' + i; })
            .style('stroke', function(d, i) { return series_colors[i % series_colors.length]; })
            .style('stroke-width', '3px')
            .attr('x1', 0).attr('x2', swatch).attr('y1', -4).attr('y2', -4);

        items.append('text')
            .attr('x', swatch + spacing)
            .attr('y', 0)
            .text(function(d) { return d; });

        // [OpenTES] A largura de cada item vem do texto já renderizado, e o
        // bloco é alinhado pela direita a partir do total. Antes cada item
        // ocupava 46 px fixos a partir de um deslocamento fixo, e o terceiro
        // caía fora da área do gráfico: numa rede trifásica, a fase C
        // simplesmente não aparecia na legenda.
        var offset = 0;
        items.each(function() {
            d3.select(this).attr('transform', 'translate(' + offset + ', 0)');
            var label = d3.select(this).select('text').node();
            offset += swatch + spacing + label.getComputedTextLength() + gap;
        });

        var used = Math.max(offset - gap, 0);
        legend.attr('transform',
                    'translate(' + (self.m.left + self.w - used) + ', 14)');
    }

    /**
     * Redraw the timeline with the new data from the timeline_buf.
     */
    function tick() {
        if (self.timeline_node === null) {
            // Break the recursion
            return;
        }
    
        var data = self.timeline_buf;
        self.timeline_buf = [];
        // [OpenTES] Uma seleção com todas as curvas do nó, em vez de uma só.
        var lines = svg.selectAll('#timeline .line');
        var datums = lines.nodes().map(function(node) {
            return d3.select(node).datum();
        });

        if (!datums.length) {
            return;
        }

        // Cada instante do buffer traz um valor por série.
        data.forEach(function(values) {
            datums.forEach(function(datum, i) {
                datum.push(Array.isArray(values) ? values[i] : values);
            });
        });

        // Update domains
        var all_values = [];
        datums.forEach(function(datum) {
            all_values = all_values.concat(plottable(datum));
        });

        self.x.domain(get_domain());
        self.y.domain([Math.min(self.y_pos, d3.min(all_values)),
                       Math.max(self.y_pos, d3.max(all_values))]);

        // slide the x-axis left
        self.x_axis.attr('transform', 'translate(0, ' + self.y(self.y_pos) + ')');
        self.x_axis.transition()
            .duration(1000)
            .ease(d3.easeLinear)
            .call(self.make_x_axis);
        self.y_axis.call(self.make_y_axis);

        // Update the lines and slide them left
        var translate_x = self.x(self.time -
                ((datums[0].length - 1) * self.update_interval));

        try {
            lines.attr('d', self.make_line)
                .attr('transform', null);
            var transition = lines.transition()
                .duration(1000)
                .ease(d3.easeLinear)
                .attr('transform', 'translate(' + translate_x + ', 0)');
            // Uma única continuação, mesmo com várias curvas: uma por curva
            // dispararia N ticks concorrentes, cada um consumindo o buffer.
            transition.on('end', function() {
                // `this` é o elemento da curva, qualquer que seja a assinatura
                // dos argumentos na versão do d3.
                if (this === lines.nodes()[0]) {
                    tick();
                }
            });
        } catch (e) {
            console.error('Error during transition:', e);
        }

        datums.forEach(function(datum) {
            while (datum.length > (self.timeline_backlog + 1)) {
                datum.shift();
            }
        });
    }
    

    /**
     * Update the timeline with new values.
     */
    function update(data) {
        self.time = self.start_date.getTime() + (data.time * 1000);
    
        // Update ring buffers with new data
        data.node_data.forEach(function(nodes) {
            // Convert nodes to a Map if it's not already one
            var nodeMap = new Map(Object.entries(nodes));
            
            nodeMap.forEach(function(v, k) {
                if (!self.backlog_data[k]) {
                    self.backlog_data[k] = new RingBuffer(self.timeline_backlog + 1, null);
                }
                // [OpenTES] O buffer guarda o vetor de valores (uma entrada por
                // fase); o agregado sozinho não permitiria desenhar as curvas
                // por fase depois.
                self.backlog_data[k].push(v.values || [v.value]);
            });

            if (self.timeline_node !== null && nodes[self.timeline_node]) {
                var incoming = nodes[self.timeline_node];
                self.timeline_buf.push(incoming.values || [incoming.value]);
            }
        });
    }
    

    return {
        init: init,
        create: create,
        update: update
    };
}


/**
 * A simple ring buffer with stores at most *size* elements.
 *
 * If it reaches its capacity and another item is pushed, the oldest item is
 * dropped.
 *
 * ``data()``
 *   Return an array containing all data. The oldest item will be at position
 *   0 and the newest item on the end.
 *
 * ``push(item)``
 *   Push *item* to the buffer removing the oldest item if necessary.
 */
function RingBuffer(size, init_val) {
    var zero = 0;  // Points to element "0"
    var buffer = [];
    for (var i = 0; i < size; i ++) {
        buffer.push(init_val);
    }

    function get(key) {
        key = (size + zero + key) % size;
        return buffer[key];
    }

    return {
        data: function() {
            ret = [];
            for (var i = 0; i < buffer.length; i ++) {
                ret.push(get(i));
            }
            return ret;
        },
        push: function(item) {
            buffer[zero] = item;
            zero = (zero + 1) % size;
        }
    };
}
