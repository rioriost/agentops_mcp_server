class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/d8/86/17a3d38bba6a12e5cb2ef156dbe3459e0ce8e5b680574afad389c1bd0e3c/agentops_mcp_server-0.4.11.tar.gz"
  sha256 "4a2fe9aef02b54abf8fd0d1e2dda632c49c0b7ed9174910061db97c3d7f9c87b"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
    prefix.install "README-jp.md"
    prefix.install "docs"
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
