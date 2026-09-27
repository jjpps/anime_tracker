import { Component, OnDestroy, inject, signal } from '@angular/core';
import { Api, Novidade, Tarefa } from './api';

@Component({
  selector: 'app-root',
  standalone: true,
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App implements OnDestroy {
  private api = inject(Api);

  novidades = signal<Novidade[]>([]);
  carregando = signal(true);
  erro = signal<string | null>(null);
  tarefa = signal<Tarefa | null>(null);

  private timer?: ReturnType<typeof setInterval>;

  constructor() {
    this.carregar();
    // se um sync já estiver rodando (recarreguei a página no meio), reengata
    this.api.tarefa().subscribe((t) => {
      this.tarefa.set(t);
      if (t.rodando) this.acompanhar();
    });
  }

  ngOnDestroy() {
    clearInterval(this.timer);
  }

  carregar() {
    this.carregando.set(true);
    this.api.novidades().subscribe({
      next: (lista) => {
        this.novidades.set(lista);
        this.carregando.set(false);
      },
      error: () => {
        this.erro.set('não consegui falar com o servidor');
        this.carregando.set(false);
      },
    });
  }

  sincronizar(force = false) {
    this.erro.set(null);
    this.api.baixarCrunchyroll(force).subscribe({
      next: () => this.acompanhar(),
      error: (e) => {
        const corpo = e?.error ?? {};
        if (e?.status === 429 && confirm(
          `Sincronizado há pouco (libera em ${corpo.minutos_ate_liberar} min). Sincronizar mesmo assim?`)) {
          this.sincronizar(true);
          return;
        }
        this.erro.set(corpo.erro ?? `falha ao iniciar (${e?.status})`);
      },
    });
  }

  private acompanhar() {
    clearInterval(this.timer);
    this.timer = setInterval(() => {
      this.api.tarefa().subscribe((t) => {
        this.tarefa.set(t);
        if (t.rodando) return;
        clearInterval(this.timer);
        if (t.erro) this.erro.set(t.erro);
        this.carregar();
      });
    }, 1000);
  }

  /** "há 3 horas": o que importa é se a lista ainda está viva. */
  ha(iso: string | null): string {
    if (!iso) return 'nunca';
    const horas = Math.floor((Date.now() - new Date(iso).getTime()) / 3_600_000);
    if (horas < 1) return 'há menos de 1 hora';
    if (horas < 48) return `há ${horas} hora${horas > 1 ? 's' : ''}`;
    return `há ${Math.floor(horas / 24)} dias`;
  }
}
