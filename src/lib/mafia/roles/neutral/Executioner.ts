import ExecutionerFaction from '@mafia/factions/neutral/Executioner';
import { allRoles } from '@mafia/roles';
import type Player from '@mafia/structures/Player';
import Role from '@mafia/structures/Role';
import { randomArrayItem } from '@util/utils';

class Executioner extends Role {
	public name = 'Executioner';
	public description = 'You must get your target eliminated by all means necessary.';
	public target!: Player;
	public faction = new ExecutionerFaction();

	public async init() {
		const targets = this.game.players.filter((player) => player.role.faction.name === 'Town' && player.role.name !== 'Mayor');
		if (targets.length === 0) {
			await this.player.user.send('There are no valid targets in game. You have become a Jester!');
			const Jester = allRoles.get('Jester')!;
			this.player.role = new Jester(this.player);
			return this.player.sendPM();
		}

		this.target = randomArrayItem(targets)!;
		return this.player.user.send(`Your target is ${this.target.user.tag}.`);
	}
}

Executioner.aliases = ['Exe'];
Executioner.categories = [...Executioner.categories, 'Neutral Evil', 'Evil'];

export default Executioner;
