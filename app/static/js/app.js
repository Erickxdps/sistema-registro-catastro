/* Circuata — comportamiento de la interfaz (sin dependencias).
 *
 *  1. Tema claro/oscuro persistente
 *  2. Menú lateral en móvil y menús de acciones
 *  3. Avisos (flash) y avisos tras recargar
 *  4. Confirmación de acciones destructivas (<dialog>)
 *  5. Prevención de envíos duplicados
 *  6. Envío automático de filtros
 *  7. Buscador con autocompletado (debounce, cancelación, teclado, caché)
 *  8. Acciones AJAX (fetch) con los contratos existentes
 *  9. Formularios que envían JSON (crear reunión / emitir cuota)
 *
 * La protección CSRF de fetch() y formularios vive en el <head> de base.html.
 */
(function () {
    'use strict';

    var $ = function (sel, ctx) { return (ctx || document).querySelector(sel); };
    var $$ = function (sel, ctx) { return Array.prototype.slice.call((ctx || document).querySelectorAll(sel)); };

    function escapar(texto) {
        var d = document.createElement('div');
        d.textContent = texto == null ? '' : String(texto);
        return d.innerHTML;
    }

    /* ── 1. Tema ─────────────────────────────────────────────────────────── */
    var raiz = document.documentElement;
    function pintarTema() {
        var oscuro = raiz.getAttribute('data-theme') === 'dark';
        $$('[data-tema]').forEach(function (btn) {
            btn.setAttribute('aria-pressed', oscuro ? 'true' : 'false');
            btn.setAttribute('aria-label', oscuro ? 'Usar modo claro' : 'Usar modo oscuro');
            btn.title = oscuro ? 'Usar modo claro' : 'Usar modo oscuro';
            var ico = $('.ico', btn);
            if (ico) ico.textContent = oscuro ? 'light_mode' : 'dark_mode';
        });
    }
    document.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-tema]');
        if (!btn) return;
        var nuevo = raiz.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
        raiz.setAttribute('data-theme', nuevo);
        try { localStorage.setItem('circuata-tema', nuevo); } catch (err) { /* sin almacenamiento */ }
        pintarTema();
    });
    pintarTema();

    /* ── 2. Menú lateral y menús de acciones ──────────────────────────────── */
    var velo = $('.velo');
    function menuLateral(abrir) {
        document.body.classList.toggle('menu-abierto', abrir);
        if (velo) velo.hidden = !abrir;
        $$('[data-menu]').forEach(function (b) { b.setAttribute('aria-expanded', abrir ? 'true' : 'false'); });
    }
    document.addEventListener('click', function (e) {
        if (e.target.closest('[data-menu]')) { menuLateral(!document.body.classList.contains('menu-abierto')); return; }
        if (e.target === velo) menuLateral(false);
        // Cerrar menús <details class="menu"> al hacer clic fuera
        $$('details.menu[open]').forEach(function (m) { if (!m.contains(e.target)) m.removeAttribute('open'); });
    });
    document.addEventListener('toggle', function (e) {
        var m = e.target;
        if (!(m instanceof HTMLDetailsElement) || !m.classList.contains('menu') || !m.open) return;
        $$('details.menu[open]').forEach(function (o) { if (o !== m) o.removeAttribute('open'); });
        var primero = $('.menu-item', m);
        if (primero) primero.focus();
    }, true);
    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        var abierto = $('details.menu[open]');
        if (abierto) { abierto.removeAttribute('open'); var s = $('summary', abierto); if (s) s.focus(); }
        if (document.body.classList.contains('menu-abierto')) menuLateral(false);
    });

    /* ── 3. Avisos ────────────────────────────────────────────────────────── */
    var contAvisos = $('.avisos');
    function cerrarAviso(aviso) {
        aviso.classList.add('saliendo');
        setTimeout(function () { aviso.remove(); }, 220);
    }
    function programarCierre(aviso) {
        if (aviso.classList.contains('aviso-error')) return; // los errores esperan a que se lean
        setTimeout(function () { if (aviso.isConnected) cerrarAviso(aviso); }, 6500);
    }
    function mostrarAviso(texto, tipo) {
        if (!contAvisos) return;
        var iconos = { error: 'error', aviso: 'warning', ok: 'check_circle' };
        var el = document.createElement('div');
        el.className = 'aviso' + (tipo === 'error' ? ' aviso-error' : tipo === 'aviso' ? ' aviso-aviso' : '');
        el.setAttribute('role', tipo === 'error' ? 'alert' : 'status');
        el.innerHTML = '<span class="ico" aria-hidden="true">' + (iconos[tipo] || 'check_circle') + '</span>' +
            '<p>' + escapar(texto) + '</p>' +
            '<button type="button" class="aviso-cerrar" aria-label="Cerrar aviso"><span class="ico" aria-hidden="true">close</span></button>';
        contAvisos.appendChild(el);
        programarCierre(el);
    }
    window.CircuataAviso = mostrarAviso;
    $$('.aviso').forEach(programarCierre);
    document.addEventListener('click', function (e) {
        var b = e.target.closest('.aviso-cerrar');
        if (b) cerrarAviso(b.closest('.aviso'));
    });
    // Aviso pendiente tras una recarga provocada por una acción AJAX
    try {
        var pendiente = sessionStorage.getItem('circuata-aviso');
        if (pendiente) {
            sessionStorage.removeItem('circuata-aviso');
            var datos = JSON.parse(pendiente);
            mostrarAviso(datos.texto, datos.tipo);
        }
    } catch (err) { /* sin almacenamiento */ }
    function recargarConAviso(texto, tipo, destino) {
        try { sessionStorage.setItem('circuata-aviso', JSON.stringify({ texto: texto, tipo: tipo || 'ok' })); } catch (err) {}
        if (destino) window.location.href = destino; else window.location.reload();
    }

    /* ── 4. Confirmación ─────────────────────────────────────────────────── */
    var dialogo = $('#dialogo-confirmar');
    function confirmar(opciones) {
        return new Promise(function (resolver) {
            if (!dialogo || typeof dialogo.showModal !== 'function') {
                resolver(window.confirm(opciones.mensaje));
                return;
            }
            $('[data-dialogo-titulo]', dialogo).textContent = opciones.titulo || '¿Confirmas esta acción?';
            $('[data-dialogo-mensaje]', dialogo).textContent = opciones.mensaje || '';
            var aceptar = $('[data-dialogo-aceptar]', dialogo);
            aceptar.textContent = opciones.accion || 'Eliminar';
            aceptar.className = 'boton ' + (opciones.peligro === false ? 'boton-principal' : 'boton-peligro');
            function cerrar(valor) {
                dialogo.removeEventListener('close', alCerrar);
                aceptar.removeEventListener('click', alAceptar);
                if (dialogo.open) dialogo.close();
                resolver(valor);
            }
            function alAceptar() { cerrar(true); }
            function alCerrar() { cerrar(false); }
            aceptar.addEventListener('click', alAceptar);
            dialogo.addEventListener('close', alCerrar);
            dialogo.showModal();
            $('[data-dialogo-cancelar]', dialogo).focus();
        });
    }
    window.CircuataConfirmar = confirmar;
    if (dialogo) {
        $('[data-dialogo-cancelar]', dialogo).addEventListener('click', function () { dialogo.close(); });
    }

    document.addEventListener('submit', function (e) {
        var form = e.target;
        if (!form.hasAttribute('data-confirm') || form.dataset.confirmado === '1') return;
        e.preventDefault();
        confirmar({
            titulo: form.getAttribute('data-confirm-titulo'),
            mensaje: form.getAttribute('data-confirm'),
            accion: form.getAttribute('data-confirm-accion'),
            peligro: form.getAttribute('data-confirm-peligro') !== 'no'
        }).then(function (ok) {
            if (!ok) return;
            form.dataset.confirmado = '1';
            if (form.requestSubmit) form.requestSubmit(); else form.submit();
        });
    });

    /* ── 5. Envíos duplicados ────────────────────────────────────────────── */
    document.addEventListener('submit', function (e) {
        var form = e.target;
        if (e.defaultPrevented) return;
        if ((form.getAttribute('method') || 'get').toLowerCase() !== 'post') return;
        if (form.dataset.enviando === '1') { e.preventDefault(); return; }
        form.dataset.enviando = '1';
        $$('button[type="submit"], button:not([type])', form).forEach(function (b) {
            b.classList.add('enviando');
            b.setAttribute('aria-disabled', 'true');
        });
    });
    // Si el usuario vuelve con "Atrás", reactivar los formularios
    window.addEventListener('pageshow', function () {
        $$('form[data-enviando="1"]').forEach(function (f) {
            delete f.dataset.enviando; delete f.dataset.confirmado;
            $$('.enviando', f).forEach(function (b) { b.classList.remove('enviando'); b.removeAttribute('aria-disabled'); });
        });
    });

    /* ── 6. Filtros que se envían solos ──────────────────────────────────── */
    document.addEventListener('change', function (e) {
        var el = e.target.closest('[data-auto]');
        if (!el || !el.form) return;
        if (el.form.requestSubmit) el.form.requestSubmit(); else el.form.submit();
    });

    /* ── 7. Buscador con autocompletado ──────────────────────────────────── */
    var RETARDO = 220;            // ms de espera tras la última tecla
    var RETARDO_CARGA = 180;      // mostrar el indicador solo si tarda
    var contador = 0;

    function Buscador(raizEl) {
        this.raiz = raizEl;
        this.url = raizEl.getAttribute('data-url');
        this.modo = raizEl.getAttribute('data-modo') || 'seleccion'; // 'seleccion' | 'navegar'
        this.minimo = parseInt(raizEl.getAttribute('data-minimo') || '1', 10);
        this.input = $('input[type="search"], input[type="text"]', raizEl);
        this.oculto = $('input[type="hidden"][data-valor]', raizEl);
        this.lista = $('.buscador-lista', raizEl);
        this.carga = $('.buscador-carga', raizEl);
        this.limpiar = $('.buscador-limpiar', raizEl);
        this.elegido = $('.buscador-elegido', raizEl);
        this.error = $('.error-campo', raizEl);
        this.cache = {};
        this.resultados = [];
        this.activo = -1;
        this.secuencia = 0;
        this.controlador = null;
        this.temporizador = null;
        this.temporizadorCarga = null;
        this.textoElegido = this.oculto && this.oculto.value ? this.input.value : null;
        var id = 'buscador-' + (++contador);
        this.lista.id = id + '-lista';
        this.input.setAttribute('role', 'combobox');
        this.input.setAttribute('aria-autocomplete', 'list');
        this.input.setAttribute('aria-expanded', 'false');
        this.input.setAttribute('aria-controls', this.lista.id);
        this.input.setAttribute('autocomplete', 'off');
        this.lista.setAttribute('role', 'listbox');
        this.prefijo = id;
        this.raiz.classList.toggle('elegido', !!(this.oculto && this.oculto.value));
        this.actualizarLimpiar();
        this.enlazar();
    }

    Buscador.prototype.enlazar = function () {
        var self = this;
        this.input.addEventListener('input', function () {
            if (self.oculto && self.textoElegido !== null && self.input.value !== self.textoElegido) {
                self.oculto.value = '';
                self.textoElegido = null;
                self.raiz.classList.remove('elegido');
                if (self.elegido) self.elegido.textContent = '';
            }
            self.marcarError('');
            self.actualizarLimpiar();
            clearTimeout(self.temporizador);
            self.temporizador = setTimeout(function () { self.buscar(self.input.value.trim()); }, RETARDO);
        });
        this.input.addEventListener('focus', function () {
            if (!self.textoElegido && self.input.value.trim().length >= self.minimo && self.resultados.length) self.abrir();
        });
        this.input.addEventListener('keydown', function (e) { self.teclado(e); });
        this.lista.addEventListener('mousedown', function (e) { e.preventDefault(); }); // no perder el foco
        this.lista.addEventListener('click', function (e) {
            var li = e.target.closest('[data-indice]');
            if (li) self.elegir(parseInt(li.getAttribute('data-indice'), 10));
        });
        if (this.limpiar) {
            this.limpiar.addEventListener('click', function () {
                self.input.value = '';
                if (self.oculto) self.oculto.value = '';
                self.textoElegido = null;
                self.raiz.classList.remove('elegido');
                if (self.elegido) self.elegido.textContent = '';
                self.cerrar();
                self.actualizarLimpiar();
                self.input.focus();
                if (self.modo === 'navegar' && self.raiz.hasAttribute('data-enviar-al-limpiar')) self.enviar();
            });
        }
        document.addEventListener('pointerdown', function (e) {
            if (!self.raiz.contains(e.target)) self.cerrar();
        });
        var form = this.input.form;
        if (form && this.modo === 'seleccion' && this.raiz.hasAttribute('data-requerido')) {
            form.addEventListener('submit', function (e) {
                if (self.oculto && !self.oculto.value) {
                    e.preventDefault();
                    e.stopImmediatePropagation();
                    self.marcarError(self.raiz.getAttribute('data-mensaje-requerido') || 'Elige una opción de la lista de sugerencias.');
                    self.input.focus();
                }
            }, true);
        }
    };

    Buscador.prototype.actualizarLimpiar = function () {
        if (this.limpiar) this.limpiar.hidden = !this.input.value;
    };

    Buscador.prototype.marcarError = function (texto) {
        if (this.error) this.error.textContent = texto;
        this.raiz.classList.toggle('invalido', !!texto);
        this.input.setAttribute('aria-invalid', texto ? 'true' : 'false');
    };

    Buscador.prototype.buscar = function (q) {
        var self = this;
        if (q.length < this.minimo) { this.resultados = []; this.cerrar(); return; }
        if (this.cache[q]) { this.pintar(q, this.cache[q]); return; }

        if (this.controlador) this.controlador.abort();      // cancela la búsqueda anterior
        this.controlador = typeof AbortController === 'function' ? new AbortController() : null;
        var miSecuencia = ++this.secuencia;
        clearTimeout(this.temporizadorCarga);
        this.temporizadorCarga = setTimeout(function () { if (self.carga) self.carga.hidden = false; }, RETARDO_CARGA);

        var url = this.url + (this.url.indexOf('?') > -1 ? '&' : '?') + 'q=' + encodeURIComponent(q);
        fetch(url, { headers: { 'Accept': 'application/json' }, credentials: 'same-origin',
                     signal: this.controlador ? this.controlador.signal : undefined })
            .then(function (r) {
                if (!r.ok) throw new Error(r.status === 401 || r.status === 302 ? 'sesion' : 'http');
                return r.json();
            })
            .then(function (datos) {
                if (miSecuencia !== self.secuencia) return;   // llegó tarde: se descarta
                self.cache[q] = datos;
                self.pintar(q, datos);
            })
            .catch(function (err) {
                if (err && err.name === 'AbortError') return;
                if (miSecuencia !== self.secuencia) return;
                self.estado('No se pudo buscar. Revisa tu conexión e inténtalo de nuevo.');
            })
            .then(function () {
                if (miSecuencia === self.secuencia) {
                    clearTimeout(self.temporizadorCarga);
                    if (self.carga) self.carga.hidden = true;
                }
            });
    };

    function resaltar(texto, q) {
        var html = escapar(texto);
        var palabras = q.split(/\s+/).filter(Boolean).map(function (p) {
            return escapar(p).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        });
        if (!palabras.length) return html;
        try {
            return html.replace(new RegExp('(' + palabras.join('|') + ')', 'gi'), '<mark>$1</mark>');
        } catch (err) { return html; }
    }

    Buscador.prototype.pintar = function (q, datos) {
        var self = this;
        this.resultados = datos.resultados || [];
        this.activo = this.resultados.length ? 0 : -1;
        if (!this.resultados.length) {
            this.estado('Sin coincidencias para “' + q + '”. Prueba con otra parte del nombre.');
            return;
        }
        var html = this.resultados.map(function (r, i) {
            return '<li role="option" class="buscador-opcion" id="' + self.prefijo + '-op' + i + '" data-indice="' + i + '"' +
                (i === self.activo ? ' aria-selected="true"' : ' aria-selected="false"') + '>' +
                '<span class="principal-op">' + resaltar(r.texto, q) + '</span>' +
                (r.detalle ? '<span class="detalle-op">' + escapar(r.detalle) + '</span>' : '') +
                '</li>';
        }).join('');
        if (datos.total > this.resultados.length) {
            html += '<li class="buscador-pie" role="presentation">Mostrando ' + this.resultados.length + ' de ' +
                datos.total + '. Escribe más para afinar.</li>';
        }
        this.lista.innerHTML = html;
        this.marcarActivo();
        this.abrir();
    };

    Buscador.prototype.estado = function (texto) {
        this.resultados = [];
        this.activo = -1;
        this.lista.innerHTML = '<li class="buscador-estado" role="presentation">' + escapar(texto) + '</li>';
        this.input.removeAttribute('aria-activedescendant');
        this.abrir();
    };

    Buscador.prototype.abrir = function () {
        this.lista.hidden = false;
        this.input.setAttribute('aria-expanded', 'true');
    };

    Buscador.prototype.cerrar = function () {
        this.lista.hidden = true;
        this.input.setAttribute('aria-expanded', 'false');
        this.input.removeAttribute('aria-activedescendant');
    };

    Buscador.prototype.marcarActivo = function () {
        var self = this;
        $$('[data-indice]', this.lista).forEach(function (li, i) {
            var sel = i === self.activo;
            li.setAttribute('aria-selected', sel ? 'true' : 'false');
            if (sel) {
                self.input.setAttribute('aria-activedescendant', li.id);
                li.scrollIntoView({ block: 'nearest' });
            }
        });
    };

    Buscador.prototype.teclado = function (e) {
        var abierta = !this.lista.hidden && this.resultados.length;
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            if (!abierta) { this.buscar(this.input.value.trim()); return; }
            this.activo = (this.activo + 1) % this.resultados.length;
            this.marcarActivo();
        } else if (e.key === 'ArrowUp') {
            if (!abierta) return;
            e.preventDefault();
            this.activo = (this.activo - 1 + this.resultados.length) % this.resultados.length;
            this.marcarActivo();
        } else if (e.key === 'Enter') {
            if (abierta && this.activo > -1) {
                e.preventDefault();
                this.elegir(this.activo);
            } else if (this.modo === 'seleccion') {
                e.preventDefault(); // en formularios, Enter sin opción no envía a medias
            }
        } else if (e.key === 'Escape') {
            if (!this.lista.hidden) { e.preventDefault(); e.stopPropagation(); this.cerrar(); }
        } else if (e.key === 'Tab') {
            this.cerrar();
        }
    };

    Buscador.prototype.elegir = function (i) {
        var r = this.resultados[i];
        if (!r) return;
        this.input.value = r.texto;
        this.cerrar();
        this.actualizarLimpiar();
        if (this.modo === 'navegar') { this.enviar(); return; }
        if (this.oculto) this.oculto.value = r.id;
        this.textoElegido = r.texto;
        this.raiz.classList.add('elegido');
        if (this.elegido) this.elegido.textContent = r.detalle || '';
        this.marcarError('');
        this.raiz.dispatchEvent(new CustomEvent('buscador:elegido', { detail: r, bubbles: true }));
    };

    Buscador.prototype.enviar = function () {
        var form = this.input.form;
        if (!form) return;
        var pagina = form.querySelector('input[name="page"]');
        if (pagina) pagina.value = '1';
        if (form.requestSubmit) form.requestSubmit(); else form.submit();
    };

    $$('[data-buscador]').forEach(function (el) { new Buscador(el); });

    /* ── 8. Acciones AJAX ────────────────────────────────────────────────── */
    // <button data-fetch="/url" data-fetch-cuerpo='{"x":1}' data-confirm="..." data-exito="...">
    document.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-fetch]');
        if (!btn) return;
        e.preventDefault();
        var ejecutar = function () {
            if (btn.classList.contains('enviando')) return;
            btn.classList.add('enviando');
            var cuerpo = btn.getAttribute('data-fetch-cuerpo');
            var opciones = { method: btn.getAttribute('data-fetch-metodo') || 'POST', credentials: 'same-origin',
                             headers: { 'Accept': 'application/json' } };
            if (cuerpo) { opciones.headers['Content-Type'] = 'application/json'; opciones.body = cuerpo; }
            fetch(btn.getAttribute('data-fetch'), opciones)
                .then(function (r) { return r.json().catch(function () { return { success: false }; }); })
                .then(function (datos) {
                    if (datos.success) {
                        recargarConAviso(btn.getAttribute('data-exito') || datos.message || 'Listo.', 'ok',
                                         btn.getAttribute('data-destino'));
                    } else {
                        btn.classList.remove('enviando');
                        mostrarAviso(datos.error || datos.message || 'No se pudo completar la acción.', 'error');
                    }
                })
                .catch(function () {
                    btn.classList.remove('enviando');
                    mostrarAviso('No hay conexión con el servidor. Inténtalo de nuevo.', 'error');
                });
        };
        var msg = btn.getAttribute('data-confirm');
        if (!msg) { ejecutar(); return; }
        confirmar({ titulo: btn.getAttribute('data-confirm-titulo'), mensaje: msg,
                    accion: btn.getAttribute('data-confirm-accion'),
                    peligro: btn.getAttribute('data-confirm-peligro') !== 'no' })
            .then(function (ok) { if (ok) ejecutar(); });
    });

    /* ── 9. Formularios que envían JSON ──────────────────────────────────── */
    // <form data-json="/api/..." data-destino="/lista"> — conserva los contratos de las API.
    $$('form[data-json]').forEach(function (form) {
        form.addEventListener('submit', function (e) {
            if (e.defaultPrevented) return;
            e.preventDefault();
            if (form.dataset.enviando === '1') return;
            form.dataset.enviando = '1';
            var datos = {};
            $$('[name]', form).forEach(function (campo) {
                if (campo.name === 'csrf_token' || campo.disabled) return;
                var v = campo.value;
                datos[campo.name] = campo.getAttribute('data-tipo') === 'numero' ? (v === '' ? null : parseFloat(v)) : v.trim();
            });
            var progreso = $('[data-progreso]', form);
            var boton = $('button[type="submit"]', form);
            if (boton) { boton.classList.add('enviando'); boton.setAttribute('aria-disabled', 'true'); }
            if (progreso) progreso.hidden = false;
            fetch(form.getAttribute('data-json'), {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
                body: JSON.stringify(datos)
            })
                .then(function (r) { return r.json().catch(function () { return { success: false }; }); })
                .then(function (res) {
                    if (res.success) {
                        recargarConAviso(res.message || 'Listo.', 'ok', form.getAttribute('data-destino'));
                        return;
                    }
                    throw new Error(res.error || 'No se pudo completar la operación.');
                })
                .catch(function (err) {
                    if (progreso) progreso.hidden = true;
                    delete form.dataset.enviando;
                    if (boton) { boton.classList.remove('enviando'); boton.removeAttribute('aria-disabled'); }
                    mostrarAviso(err.message && err.message !== 'Failed to fetch' ? err.message
                        : 'No hay conexión con el servidor. Inténtalo de nuevo.', 'error');
                });
        });
    });
})();
