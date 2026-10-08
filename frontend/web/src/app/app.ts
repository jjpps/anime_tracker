import { Component, HostListener, OnDestroy, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { Api, Tarefa } from './api';

/** Casca: navbar, mega menu, estado do sync e a página da rota. */
@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App implements OnDestroy {
  api = inject(Api);

  tarefa = signal<Tarefa | null>(null);
  menuAberto = signal(false);

  private timer?: ReturnType<typeof setInterval>;

  constructor() {
    this.api.recarregarStats();
    // se um sync já estiver rodando (recarreguei a página no meio), reengata
    this.api.tarefa().subscribe((t) => {
      this.tarefa.set(t);
      if (t.rodando) this.acompanhar();
    });
  }

  ngOnDestroy() {
    clearInterval(this.timer);
  }

  alternarMenu() {
    this.menuAberto.update((v) => !v);
    if (this.menuAberto()) this.api.recarregarStats();
  }

  @HostListener('document:keydown.escape')
  fecharMenu() {
    this.menuAberto.set(false);
  }

  sincronizar(force = false) {
    this.api.erro.set(null);
    this.api.baixarCrunchyroll(force).subscribe({
      next: () => this.acompanhar(),
      error: (e) => {
        const corpo = e?.error ?? {};
        if (e?.status === 429 && confirm(
          `Sincronizado há pouco (libera em ${corpo.minutos_ate_liberar} min). Sincronizar mesmo assim?`)) {
          this.sincronizar(true);
          return;
        }
        this.api.erro.set(corpo.erro ?? `falha ao iniciar (${e?.status})`);
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
        if (t.erro) this.api.erro.set(t.erro);
        this.api.versao.update((v) => v + 1);
        this.api.recarregarStats();
      });
    }, 1000);
  }

  /** "há 3 horas": o que importa é se a lista ainda está viva. */
  ha(iso: string | null | undefined): string {
    if (!iso) return 'nunca';
    const horas = Math.floor((Date.now() - new Date(iso).getTime()) / 3_600_000);
    if (horas < 1) return 'há menos de 1 hora';
    if (horas < 48) return `há ${horas} hora${horas > 1 ? 's' : ''}`;
    return `há ${Math.floor(horas / 24)} dias`;
  }
}
