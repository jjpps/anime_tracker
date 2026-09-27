import { Component, effect, inject, signal } from '@angular/core';
import { AnimeCard } from './anime-card';
import { Api, Novidade } from './api';

@Component({
  selector: 'app-novidades',
  standalone: true,
  imports: [AnimeCard],
  template: `
    <h1 class="h5 mb-3">Novidades <small class="text-secondary">({{ lista().length }})</small></h1>

    @if (carregando()) {
      <p class="text-secondary">carregando...</p>
    } @else if (!lista().length) {
      <p class="text-secondary">Nada novo nos animes que você começou.</p>
    } @else {
      <div class="row row-cols-2 row-cols-sm-3 row-cols-md-4 row-cols-xl-5 g-3">
        @for (a of lista(); track a.series_id) {
          <div class="col">
            <app-anime-card [seriesId]="a.series_id" [title]="a.title" [poster]="a.poster">
              @for (t of a.new_seasons; track t.title) {
                <div class="small mb-1">
                  <span class="badge text-bg-primary">Temporada nova</span>
                  <div class="text-body-secondary">{{ t.title }} · {{ t.episodes }} eps</div>
                </div>
              }
              @if (a.continuation; as c) {
                <div class="small">
                  <span class="badge text-bg-info">Continuação</span>
                  <div class="text-body-secondary">{{ c.episodes }} eps novos em {{ c.title }}</div>
                </div>
              }
              <button acao class="btn btn-outline-secondary btn-sm w-100" (click)="parar(a)">
                Parar de acompanhar
              </button>
            </app-anime-card>
          </div>
        }
      </div>
    }
  `,
})
export class NovidadesPage {
  private api = inject(Api);

  lista = signal<Novidade[]>([]);
  carregando = signal(true);

  constructor() {
    // recarrega quando um sync termina
    effect(() => {
      this.api.versao();
      this.carregar();
    });
  }

  private carregar() {
    this.api.novidades().subscribe({
      next: (l) => {
        this.lista.set(l);
        this.carregando.set(false);
      },
      error: () => {
        this.api.erro.set('não consegui carregar as novidades');
        this.carregando.set(false);
      },
    });
  }

  /** Tira da tela na hora; se o servidor recusar, devolve para o mesmo lugar. */
  parar(a: Novidade) {
    const antes = this.lista();
    this.lista.set(antes.filter((x) => x.series_id !== a.series_id));
    this.api.pararDeAcompanhar(a.series_id).subscribe({
      next: () => this.api.recarregarStats(),
      error: () => {
        this.lista.set(antes);
        this.api.erro.set(`não consegui parar de acompanhar ${a.title}`);
      },
    });
  }
}
