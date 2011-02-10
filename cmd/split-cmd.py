#!/usr/bin/env python
import sys, time
from bup import hashsplit, git, options, client
from bup.helpers import *


optspec = """
bup split [-tcb] [-n name] [--bench] [filenames...]
--
r,remote=  remote repository path
b,blobs    output a series of blob ids
t,tree     output a tree id
c,commit   output a commit id
n,name=    name of backup set to update (if any)
d,date=    date for the commit (seconds since the epoch)
q,quiet    don't print progress messages
v,verbose  increase log output (can be used more than once)
git-ids    read a list of git object ids from stdin and split their contents
keep-boundaries  don't let one chunk span two input files
noop       don't actually save the data anywhere
copy       just copy input to output, hashsplitting along the way
bench      print benchmark timings to stderr
max-pack-size=  maximum bytes in a single pack
max-pack-objects=  maximum number of objects in a single pack
fanout=    maximum number of blobs in a single tree
bwlimit=   maximum bytes/sec to transmit to server
"""
o = options.Options(optspec)
(opt, flags, extra) = o.parse(sys.argv[1:])

handle_ctrl_c()
git.check_repo_or_die()
if not (opt.blobs or opt.tree or opt.commit or opt.name or
        opt.noop or opt.copy):
    o.fatal("use one or more of -b, -t, -c, -n, -N, --copy")
if (opt.noop or opt.copy) and (opt.blobs or opt.tree or 
                               opt.commit or opt.name):
    o.fatal('-N and --copy are incompatible with -b, -t, -c, -n')
if extra and opt.git_ids:
    o.fatal("don't provide filenames when using --git-ids")

if opt.verbose >= 2:
    git.verbose = opt.verbose - 1
    opt.bench = 1
if opt.max_pack_size:
    hashsplit.max_pack_size = parse_num(opt.max_pack_size)
if opt.max_pack_objects:
    hashsplit.max_pack_objects = parse_num(opt.max_pack_objects)
if opt.fanout:
    hashsplit.fanout = parse_num(opt.fanout)
if opt.blobs:
    hashsplit.fanout = 0
if opt.bwlimit:
    client.bwlimit = parse_num(opt.bwlimit)
if opt.date:
    date = parse_date_or_fatal(opt.date, o.fatal)
else:
    date = time.time()


last_prog = total_bytes = 0
def prog(filenum, nbytes):
    global last_prog, total_bytes
    total_bytes += nbytes
    now = time.time()
    if now - last_prog < 0.2:
        return
    if filenum > 0:
        progress('Splitting: file #%d, %d kbytes\r'
                 % (filenum+1, total_bytes/1024))
    else:
        progress('Splitting: %d kbytes\r' % (total_bytes/1024))
    last_prog = now


is_reverse = os.environ.get('BUP_SERVER_REVERSE')
if is_reverse and opt.remote:
    o.fatal("don't use -r in reverse mode; it's automatic")
start_time = time.time()

if opt.name and opt.name.startswith('.'):
    o.fatal("'%s' is not a valid branch name." % opt.name)
refname = opt.name and 'refs/heads/%s' % opt.name or None
if opt.noop or opt.copy:
    cli = pack_writer = oldref = None
elif opt.remote or is_reverse:
    cli = client.Client(opt.remote)
    oldref = refname and cli.read_ref(refname) or None
    pack_writer = cli.new_packwriter()
else:
    cli = None
    oldref = refname and git.read_ref(refname) or None
    pack_writer = git.PackWriter()

if opt.git_ids:
    # the input is actually a series of git object ids that we should retrieve
    # and split.
    #
    # This is a bit messy, but basically it converts from a series of
    # CatPipe.get() iterators into a series of file-type objects.
    # It would be less ugly if either CatPipe.get() returned a file-like object
    # (not very efficient), or split_to_shalist() expected an iterator instead
    # of a file.
    cp = git.CatPipe()
    class IterToFile:
        def __init__(self, it):
            self.it = iter(it)
        def read(self, size):
            v = next(self.it)
            return v or ''
    def read_ids():
        while 1:
            line = sys.stdin.readline()
            if not line:
                break
            if line:
                line = line.strip()
            try:
                it = cp.get(line.strip())
                next(it)  # skip the file type
            except KeyError, e:
                add_error('error: %s' % e)
                continue
            yield IterToFile(it)
    files = read_ids()
else:
    # the input either comes from a series of files or from stdin.
    files = extra and (open(fn) for fn in extra) or [sys.stdin]

if pack_writer:
    shalist = hashsplit.split_to_shalist(pack_writer, files,
                                         keep_boundaries=opt.keep_boundaries,
                                         progress=prog)
    tree = pack_writer.new_tree(shalist)
else:
    last = 0
    for (blob, bits) in hashsplit.hashsplit_iter(files,
                                    keep_boundaries=opt.keep_boundaries,
                                    progress=prog):
        hashsplit.total_split += len(blob)
        if opt.copy:
            sys.stdout.write(str(blob))
        megs = hashsplit.total_split/1024/1024
        if not opt.quiet and last != megs:
            progress('%d Mbytes read\r' % megs)
            last = megs
    progress('%d Mbytes read, done.\n' % megs)

if opt.verbose:
    log('\n')
if opt.blobs:
    for (mode,name,bin) in shalist:
        print bin.encode('hex')
if opt.tree:
    print tree.encode('hex')
if opt.commit or opt.name:
    msg = 'bup split\n\nGenerated by command:\n%r' % sys.argv
    ref = opt.name and ('refs/heads/%s' % opt.name) or None
    commit = pack_writer.new_commit(oldref, tree, date, msg)
    if opt.commit:
        print commit.encode('hex')

if pack_writer:
    pack_writer.close()  # must close before we can update the ref

if opt.name:
    if cli:
        cli.update_ref(refname, commit, oldref)
    else:
        git.update_ref(refname, commit, oldref)

if cli:
    cli.close()

secs = time.time() - start_time
size = hashsplit.total_split
if opt.bench:
    log('\nbup: %.2fkbytes in %.2f secs = %.2f kbytes/sec\n'
        % (size/1024., secs, size/1024./secs))

if saved_errors:
    log('WARNING: %d errors encountered while saving.\n' % len(saved_errors))
    sys.exit(1)
