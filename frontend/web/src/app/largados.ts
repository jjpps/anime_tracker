import { Component, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { AnimeCard } from './anime-card';
import { Api, Largado } from './api';

@Component({
  selector: 'app-largados',
  standalone: true,
  imports: [AnimeCard, DatePipe],
  template: `
    <h1 class="h5 mb-1">Parei de acompanhar <small class="text-secondary">({{ lista().length }})</small></h1>
    <p class="text-secondary small mb-3">
      Estes animes não aparecem nas novidades, nem quando sai temporada nova.
    </p>

    @if (carregando()) {
      <p class="text-secondary">carregando...</p>
    } @else if (!lista().length) {
      <p class="text-secondary">Nenhum anime largado.</p>
    } @else {
      <div class="row row-cols-2 row-cols-sm-3 row-cols-md-4 row-cols-xl-5 g-3">
        @for (a of lista(); track a.series_id) {
          <div class="col">
            <app-anime-card [seriesId]="a.series_id" [title]="a.title" [poster]="a.poster">
              <div class="small text-body-secondary">largado em {{ a.dropped_at | date: 'dd/MM/yyyy' }}</div>
              <button acao class="btn btn-outline-primary btn-sm w-100" (click)="voltar(a)">
                Voltar a acompanhar
              </button>
            </app-anime-card>
          </div>
        }
      </div>
    }
  `,
})
export class LargadosPage {
  private api = inject(Api);

  lista = signal<Largado[]>([]);
  carregando = signal(true);

  constructor() {
    this.api.largados().subscribe({
      next: (l) => {
        this.lista.set(l);
        this.carregando.set(false);
      },
      error: () => {
        this.api.erro.set('não consegui carregar os largados');
        this.carregando.set(false);
      },
    });
  }

  voltar(a: Largado) {
    const antes = this.lista();
    this.lista.set(antes.filter((x) => x.series_id !== a.series_id));
    this.api.voltarAAcompanhar(a.series_id).subscribe({
      next: () => this.api.recarregarStats(),
      error: () => {
        this.lista.set(antes);
        this.api.erro.set(`não consegui voltar a acompanhar ${a.title}`);
      },
    });
  }
}
